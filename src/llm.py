"""Model access (OpenRouter) with the failure handling A11 asks for.

* timeout + bounded retries with exponential backoff (429 / 5xx / network)
* circuit breaker: after N consecutive failures stop calling for a cool-down, so an outage does
  not turn a 120-ticket run into a 2-hour run; callers get `LLMResult.ok == False` and degrade
* disk cache (sqlite): saves free-tier allowance and makes development runs reproducible
Never raises to the caller.
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import threading
import time
from dataclasses import dataclass
from typing import Optional

import requests

from . import config

log = logging.getLogger(__name__)
URL = "https://openrouter.ai/api/v1/chat/completions"


@dataclass
class LLMResult:
    ok: bool
    text: str = ""
    latency_s: float = 0.0
    cached: bool = False
    error: str = ""
    model: str = ""


class LLMClient:
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None, use_cache: bool = True,
                 enabled: Optional[bool] = None, breaker_threshold: int = 5, breaker_cooldown_s: float = 10.0):
        self.api_key = (api_key if api_key is not None else config.OPENROUTER_API_KEY).strip()
        self.model = model or config.MODEL_NAME
        self.enabled = config.LLM_ENABLED if enabled is None else enabled
        self.use_cache = use_cache
        self.threshold, self.cooldown = breaker_threshold, breaker_cooldown_s
        self._fails, self._open_until = 0, 0.0
        self._lock = threading.Lock()
        self.stats = {"calls": 0, "cache_hits": 0, "failures": 0, "short_circuited": 0}
        self._db = None
        if use_cache:
            try:
                config.LLM_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
                self._db = sqlite3.connect(str(config.LLM_CACHE_PATH), check_same_thread=False)
                self._db.execute("CREATE TABLE IF NOT EXISTS c (k TEXT PRIMARY KEY, v TEXT, lat REAL)")
            except Exception:
                self._db = None

    def _key(self, messages, json_mode):
        return hashlib.sha256(json.dumps([self.model, messages, json_mode], sort_keys=True).encode()).hexdigest()

    def _breaker_open(self) -> bool:
        with self._lock:
            return time.time() < self._open_until

    def _record(self, ok: bool):
        with self._lock:
            if ok:
                self._fails = 0
            else:
                self._fails += 1
                self.stats["failures"] += 1
                if self._fails >= self.threshold:
                    self._open_until = time.time() + self.cooldown
                    self._fails = 0
                    log.warning("LLM circuit breaker open for %.0fs", self.cooldown)

    def chat(self, messages: list[dict], json_mode: bool = True, max_tokens: int = 350) -> LLMResult:
        if not self.enabled:
            return LLMResult(False, error="llm_disabled", model=self.model)
        if not self.api_key:
            return LLMResult(False, error="no_api_key", model=self.model)
        key = self._key(messages, json_mode)
        if self._db is not None:
            try:
                with self._lock:
                    row = self._db.execute("SELECT v, lat FROM c WHERE k=?", (key,)).fetchone()
                if row:
                    self.stats["cache_hits"] += 1
                    return LLMResult(True, row[0], row[1], cached=True, model=self.model)
            except Exception:
                pass
        if self._breaker_open():
            self.stats["short_circuited"] += 1
            return LLMResult(False, error="circuit_open", model=self.model)
        body = {"model": self.model, "messages": messages, "temperature": 0, "max_tokens": max_tokens}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        err = ""
        t0 = time.time()
        for attempt in range(config.LLM_MAX_RETRIES + 1):
            try:
                self.stats["calls"] += 1
                r = requests.post(URL, headers={"Authorization": f"Bearer {self.api_key}"}, json=body,
                                  timeout=config.LLM_TIMEOUT_S)
                if r.status_code == 200:
                    text = r.json()["choices"][0]["message"]["content"] or ""
                    lat = time.time() - t0
                    self._record(True)
                    if self._db is not None and text:
                        try:
                            with self._lock:
                                self._db.execute("INSERT OR REPLACE INTO c VALUES (?,?,?)", (key, text, lat))
                                self._db.commit()
                        except Exception:
                            pass
                    return LLMResult(True, text, lat, model=self.model)
                err = f"http_{r.status_code}"
                if r.status_code in (401, 402, 403, 404):   # not retryable
                    break
                wait = min(float(r.headers.get("Retry-After", 2 ** attempt)), 10) if r.status_code == 429 else 2 ** attempt
            except (requests.Timeout, requests.ConnectionError) as e:
                err, wait = type(e).__name__, 2 ** attempt
            except Exception as e:   # malformed body etc.
                err, wait = f"error_{type(e).__name__}", 1
            if attempt < config.LLM_MAX_RETRIES:
                time.sleep(wait)
        self._record(False)
        return LLMResult(False, latency_s=time.time() - t0, error=err, model=self.model)
