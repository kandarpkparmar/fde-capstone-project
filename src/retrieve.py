"""FR-03 Retrieve: search the documentation corpus, return ranked passages with real identifiers (A4).

* Chunking is a decision (docs/decisions/chunking.md): by default one chunk per markdown section,
  each prefixed with the article title, so a Resolution sequence is never split. Alternatives are
  measured in evaluation/chunking_experiment.py.
* Dense embeddings (all-MiniLM-L6-v2) in a persistent Chroma collection. If the embedding model or
  Chroma cannot load, degrade to an in-memory TF-IDF index instead of failing (A11).
* A relevance floor: below it we return nothing rather than something irrelevant.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

import numpy as np

from . import config

log = logging.getLogger(__name__)


@dataclass
class Passage:
    passage_id: str     # e.g. DOC-AUTH-001::resolution  (resolves to a real chunk of a real doc)
    doc_id: str
    title: str
    section: str
    text: str
    score: float = 0.0

    def to_dict(self):
        return asdict(self)


# ---------------------------------------------------------------- chunking
_H2 = re.compile(r"^## +(.+)$", re.M)


def chunk_doc(doc: dict, strategy: str = "section") -> list[Passage]:
    did, title, content = doc["doc_id"], doc.get("title", ""), doc.get("content", "")
    if strategy == "whole":
        return [Passage(f"{did}::full", did, title, "full", content)]
    if strategy == "section":
        parts = _H2.split(content)
        head = parts[0].strip()
        out = []
        for i in range(1, len(parts), 2):
            sec, body = parts[i].strip(), parts[i + 1].strip()
            slug = re.sub(r"[^a-z0-9]+", "-", sec.lower()).strip("-")
            out.append(Passage(f"{did}::{slug}", did, title, sec, f"{title} - {sec}\n{body}"))
        if not out:
            out = [Passage(f"{did}::full", did, title, "full", content)]
        return out
    if strategy.startswith("fixed"):
        size = int(strategy[5:] or 400)
        overlap = max(20, size // 6)
        out, i, n = [], 0, 0
        while i < len(content):
            seg = content[i:i + size]
            out.append(Passage(f"{did}::c{n}", did, title, f"chunk {n}", f"{title}\n{seg}"))
            n += 1
            if i + size >= len(content):
                break
            i += size - overlap
        return out
    raise ValueError(f"unknown chunk strategy {strategy}")


def load_docs(path: Optional[Path] = None) -> list[dict]:
    path = path or (config.DATA_DIR / "documentation.json")
    return json.loads(Path(path).read_text())


# ---------------------------------------------------------------- retriever
class Retriever:
    def __init__(self, docs: Optional[list[dict]] = None, strategy: Optional[str] = None,
                 backend: str = "auto", persist: bool = True, min_score: Optional[float] = None):
        self.docs = docs if docs is not None else load_docs()
        self.strategy = strategy or config.CHUNK_STRATEGY
        self.passages: list[Passage] = [p for d in self.docs for p in chunk_doc(d, self.strategy)]
        self.by_id = {p.passage_id: p for p in self.passages}
        self.doc_ids = {d["doc_id"] for d in self.docs}
        self.backend = "none"
        self._model = self._emb = self._coll = self._tfidf = self._tf_mat = None
        want_dense = backend in ("auto", "dense")
        if want_dense:
            try:
                self._init_dense(persist)
                self.backend = "dense"
            except Exception as e:
                log.warning("dense retrieval unavailable (%s); using TF-IDF fallback", type(e).__name__)
        if self.backend == "none":
            self._init_tfidf()
            self.backend = "tfidf"
        default_min = config.RETRIEVAL_MIN_SCORE if self.backend == "dense" else 0.12
        self.min_score = default_min if min_score is None else min_score

    # -- dense
    def _init_dense(self, persist: bool):
        from sentence_transformers import SentenceTransformer
        self._model = SentenceTransformer(config.EMBEDDING_MODEL)
        texts = [p.text for p in self.passages]
        self._emb = np.asarray(self._model.encode(texts, normalize_embeddings=True, show_progress_bar=False))
        try:
            import chromadb
            client = chromadb.PersistentClient(path=str(config.CHROMA_PATH)) if persist else chromadb.EphemeralClient()
            name = f"kb_{self.strategy}"
            try:
                client.delete_collection(name)
            except Exception:
                pass
            self._coll = client.create_collection(name, metadata={"hnsw:space": "cosine"})
            self._coll.add(ids=[p.passage_id for p in self.passages], embeddings=self._emb.tolist(),
                           documents=texts, metadatas=[{"doc_id": p.doc_id, "section": p.section}
                                                       for p in self.passages])
        except Exception as e:   # numpy search over the same embeddings still works
            log.warning("chroma unavailable (%s); using in-memory dense search", type(e).__name__)
            self._coll = None

    # -- tfidf fallback
    def _init_tfidf(self):
        from sklearn.feature_extraction.text import TfidfVectorizer
        self._tfidf = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, stop_words="english")
        self._tf_mat = self._tfidf.fit_transform([p.text for p in self.passages])

    def search(self, query: str, top_k: Optional[int] = None, apply_floor: bool = True) -> list[Passage]:
        top_k = top_k or config.RETRIEVAL_TOP_K
        if not query or not query.strip():
            return []
        try:
            if self.backend == "dense":
                q = np.asarray(self._model.encode([query], normalize_embeddings=True, show_progress_bar=False))[0]
                sims = self._emb @ q
            else:
                sims = (self._tf_mat @ self._tfidf.transform([query]).T).toarray().ravel()
        except Exception as e:
            log.warning("retrieval failure: %s", type(e).__name__)
            return []
        order = np.argsort(-sims, kind="stable")[:top_k]
        res = []
        for j in order:
            p = self.passages[j]
            if apply_floor and sims[j] < self.min_score:
                continue
            res.append(Passage(p.passage_id, p.doc_id, p.title, p.section, p.text, round(float(sims[j]), 4)))
        return res

    def resolve(self, passage_id: str) -> Optional[Passage]:
        return self.by_id.get(passage_id)


def top_docs(passages: list[Passage]) -> list[str]:
    seen, out = set(), []
    for p in passages:
        if p.doc_id not in seen:
            seen.add(p.doc_id)
            out.append(p.doc_id)
    return out
