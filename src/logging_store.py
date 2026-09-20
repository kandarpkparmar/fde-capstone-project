"""FR-08 Decision log (A8). SQLite, one row per automated decision, schema per Governance Framework.

Stages: classification | routing | generation | validation | outcome.
Exactly one `outcome` row is written per processed ticket, so `reconcile()` can count
logged outcomes against tickets processed. Writes are serialised with a lock.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from . import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions (
    decision_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    ticket_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    input_summary TEXT,
    model TEXT,
    prediction TEXT,
    confidence REAL,
    alternatives TEXT,
    sources_used TEXT,
    threshold_applied REAL,
    action_taken TEXT NOT NULL,
    reason TEXT NOT NULL,
    guardrail_results TEXT,
    prompt_version TEXT,
    requirement_ids TEXT
);
CREATE INDEX IF NOT EXISTS ix_dec_run ON decisions(run_id, ticket_id);
"""


class DecisionLog:
    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path or config.DB_PATH)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def log(self, run_id: str, ticket_id: str, stage: str, action_taken: str, reason: str, *,
            input_summary: str = "", model: Any = None, prediction: Any = None,
            confidence: Optional[float] = None, alternatives: Any = None, sources_used: Any = None,
            threshold_applied: Optional[float] = None, guardrail_results: Any = None,
            prompt_version: str = "", requirement_ids: Any = None) -> str:
        did = uuid.uuid4().hex
        row = (did, run_id, datetime.now(timezone.utc).isoformat(), ticket_id, stage,
               input_summary[:300], json.dumps(model), json.dumps(prediction), confidence,
               json.dumps(alternatives), json.dumps(sources_used), threshold_applied,
               action_taken, reason, json.dumps(guardrail_results), prompt_version,
               json.dumps(requirement_ids))
        with self._lock:
            self._conn.execute("INSERT INTO decisions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", row)
            self._conn.commit()
        return did

    def reconcile(self, run_id: str, tickets_processed: int) -> dict:
        with self._lock:
            cur = self._conn.cursor()
            outcomes = cur.execute("SELECT COUNT(*), COUNT(DISTINCT ticket_id) FROM decisions "
                                   "WHERE run_id=? AND stage='outcome'", (run_id,)).fetchone()
            total = cur.execute("SELECT COUNT(*) FROM decisions WHERE run_id=?", (run_id,)).fetchone()[0]
            by_stage = dict(cur.execute("SELECT stage, COUNT(*) FROM decisions WHERE run_id=? GROUP BY stage",
                                        (run_id,)).fetchall())
        return {
            "run_id": run_id, "tickets_processed": tickets_processed, "decisions_logged": total,
            "outcome_rows": outcomes[0], "distinct_tickets_with_outcome": outcomes[1],
            "by_stage": by_stage,
            "reconciles": outcomes[0] == tickets_processed == outcomes[1],
        }

    def rows(self, run_id: str, stage: Optional[str] = None) -> list[dict]:
        q = "SELECT * FROM decisions WHERE run_id=?" + (" AND stage=?" if stage else "")
        with self._lock:
            cur = self._conn.execute(q, (run_id, stage) if stage else (run_id,))
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]

    def close(self):
        with self._lock:
            self._conn.close()
