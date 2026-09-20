"""FR-02 Classify: intent + urgency with numeric confidence (A3), plus an answerability estimate.

Design decision (docs/architecture.md): a classical calibrated model (TF-IDF + logistic regression)
rather than an LLM call. It is deterministic (A5), free, fast, and its probabilities can be
calibration-checked, which is what makes the routing threshold meaningful.
Trained at start-up from data/development_tickets.json only (validation/hidden sets never used).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import joblib
import numpy as np
from scipy.sparse import hstack
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression

from . import config
from .ingest import Ticket

log = logging.getLogger(__name__)
FALLBACK_INTENT = "unclear_request"


@dataclass
class Classification:
    intent: str
    intent_confidence: float
    urgency: str
    urgency_confidence: float
    answerable_prob: float
    alternatives: list = field(default_factory=list)   # [{"value":..., "confidence":...}]
    fallback: bool = False
    note: str = ""


def _feat(t: Ticket) -> str:
    return f"{t.text} chan_{t.channel}"


class _Model:
    def __init__(self, C: float = 10.0):
        self.word = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, min_df=1, lowercase=True)
        self.char = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True, min_df=2)
        self.C = C
        self.clf = LogisticRegression(C=C, max_iter=3000)

    def _x(self, texts, fit=False):
        if fit:
            return hstack([self.word.fit_transform(texts), self.char.fit_transform(texts)]).tocsr()
        return hstack([self.word.transform(texts), self.char.transform(texts)]).tocsr()

    def fit(self, texts, y):
        self.clf.fit(self._x(texts, fit=True), y)
        return self

    def proba(self, texts):
        return self.clf.predict_proba(self._x(texts))

    @property
    def classes(self):
        return list(self.clf.classes_)


class TicketClassifier:
    def __init__(self):
        self.intent = _Model(C=10.0)
        self.urgency = _Model(C=3.0)
        self.answerable = _Model(C=3.0)
        self.temperature = 1.0   # calibration temperature for intent probs (fit in fit())
        self.intent_docs: dict = {}   # intent -> set of doc ids that answer it (from dev labels)
        self.ready = False

    # -- training -------------------------------------------------------------------
    def fit(self, tickets: list[Ticket], labels: list[dict], temperature: Optional[float] = None):
        X = [_feat(t) for t in tickets]
        self.intent.fit(X, [l["intent"] for l in labels])
        self.urgency.fit(X, [l["urgency"] for l in labels])
        self.answerable.fit(X, [bool(l["answerable_from_docs"]) for l in labels])
        if temperature is not None:
            self.temperature = temperature
        docs: dict = {}
        for l in labels:
            docs.setdefault(l["intent"], set()).update(l.get("expected_doc_ids") or [])
        self.intent_docs = docs
        self.ready = True
        return self

    def _calibrated(self, p: np.ndarray) -> np.ndarray:
        if self.temperature == 1.0:
            return p
        z = np.log(np.clip(p, 1e-9, 1)) / self.temperature
        z -= z.max(axis=1, keepdims=True)
        e = np.exp(z)
        return e / e.sum(axis=1, keepdims=True)

    # -- inference ------------------------------------------------------------------
    def predict_batch(self, tickets: list[Ticket]) -> list[Classification]:
        X = [_feat(t) for t in tickets]
        pi = self._calibrated(self.intent.proba(X))
        pu = self.urgency.proba(X)
        pa = self.answerable.proba(X)
        a_true = self.answerable.classes.index(True)
        out = []
        for i, t in enumerate(tickets):
            if not t.text.strip():
                out.append(Classification(FALLBACK_INTENT, 0.0, "medium", 0.0, 0.0,
                                          fallback=True, note="empty ticket: fallback class"))
                continue
            order = np.argsort(-pi[i])
            alts = [{"value": self.intent.classes[j], "confidence": round(float(pi[i][j]), 4)}
                    for j in order[:3]]
            u = int(np.argmax(pu[i]))
            out.append(Classification(
                intent=self.intent.classes[order[0]], intent_confidence=round(float(pi[i][order[0]]), 4),
                urgency=self.urgency.classes[u], urgency_confidence=round(float(pu[i][u]), 4),
                answerable_prob=round(float(pa[i][a_true]), 4), alternatives=alts))
        return out

    def predict(self, ticket: Ticket) -> Classification:
        try:
            return self.predict_batch([ticket])[0]
        except Exception as e:   # defined fallback rather than an exception (spec: Classify)
            log.exception("classifier failure")
            return Classification(FALLBACK_INTENT, 0.0, "medium", 0.0, 0.0, fallback=True,
                                  note=f"classifier error: {type(e).__name__}")


def load_dev(data_dir: Path = None):
    from .ingest import normalise
    data_dir = data_dir or config.DATA_DIR
    raw = json.loads((data_dir / "development_tickets.json").read_text())
    return [normalise(r) for r in raw], [r["labels"] for r in raw]


def get_classifier(force_retrain: bool = False) -> TicketClassifier:
    """Load the cached model or train from the development set (a few seconds)."""
    p = config.MODEL_CACHE_PATH
    if p.exists() and not force_retrain:
        try:
            return joblib.load(p)
        except Exception:
            log.warning("classifier cache unreadable; retraining")
    tickets, labels = load_dev()
    tf = 1.0
    tp = config.STORAGE_DIR / "temperature.json"
    if tp.exists():
        tf = json.loads(tp.read_text()).get("temperature", 1.0)
    else:
        from .calibration_defaults import DEFAULT_TEMPERATURE
        tf = DEFAULT_TEMPERATURE
    clf = TicketClassifier().fit(tickets, labels, temperature=tf)
    p.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(clf, p)
    return clf
