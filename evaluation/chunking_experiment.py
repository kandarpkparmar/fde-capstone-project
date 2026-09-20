"""Measures retrieval quality for several chunking strategies (report section 5, decision D-02).

Metric: doc-level hit@k (any expected doc in the top-k passages' documents) and MRR on the
development tickets that are answerable from the docs. Uses development data only.
Usage: python -m evaluation.chunking_experiment
"""
import json
import sys
from pathlib import Path

from src import config
from src.ingest import normalise
from src.retrieve import Retriever, load_docs, top_docs


def run(strategies=("whole", "section", "fixed800", "fixed400", "fixed250"), k=4):
    dev = json.loads((config.DATA_DIR / "development_tickets.json").read_text())
    tickets = [t for t in dev if t["labels"]["answerable_from_docs"] and t["labels"]["expected_doc_ids"]]
    docs = load_docs()
    rows = []
    for s in strategies:
        r = Retriever(docs, strategy=s, backend="dense", persist=False)
        hit = rr = 0
        scores = []
        for t in tickets:
            q = normalise(t).text
            ds = top_docs(r.search(q, top_k=k, apply_floor=False)) if s == "whole" else \
                top_docs(r.search(q, top_k=k * 2, apply_floor=False))[:k]
            exp = set(t["labels"]["expected_doc_ids"])
            ranks = [i for i, d in enumerate(ds) if d in exp]
            hit += bool(ranks)
            rr += (1 / (ranks[0] + 1)) if ranks else 0
        rows.append({"strategy": s, "chunks": len(r.passages), "hit_at_%d" % k: round(hit / len(tickets), 4),
                     "mrr": round(rr / len(tickets), 4), "n_tickets": len(tickets)})
        print(rows[-1], flush=True)
    return rows


if __name__ == "__main__":
    out = run()
    p = Path(config.ROOT / "evaluation" / "results" / "chunking_experiment.json")
    p.write_text(json.dumps(out, indent=2))
    print("wrote", p)
