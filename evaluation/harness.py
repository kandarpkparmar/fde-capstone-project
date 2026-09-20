"""Unattended evaluation harness (A9, A10).

    python -m evaluation.harness --input data/validation_tickets.json --output evaluation/results/val_run

* Takes ANY file with the ticket schema (list of tickets, or {"tickets": [...]}); the hidden set is run this way.
* Processes every ticket; a bad record or failing stage becomes a logged escalation, never a crash or a skip.
* Writes results.jsonl, metrics.json, metrics_report.md, decisions.csv, review_sample.csv into --output.
* Exit code 0 if the run completed (even with degraded tickets); 2 only if the input file cannot be read at all.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import random
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from src import config
from src.llm import LLMClient
from src.logging_store import DecisionLog
from src.pipeline import SupportPipeline

from . import report_metrics
from .judge import run_judge

log = logging.getLogger("harness")


def load_tickets(path: Path):
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        raw = raw.get("tickets") or raw.get("data") or [raw]
    if not isinstance(raw, list):
        raise ValueError("input must be a JSON list of tickets")
    return raw


def load_truth(path: Path):
    try:
        return {g["ticket_id"]: g for g in json.loads(path.read_text())}
    except Exception:
        return {}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Run the support pipeline over a ticket file and write a metrics report.")
    ap.add_argument("--input", required=True, help="path to a JSON file of tickets (schema in the Dataset Guide)")
    ap.add_argument("--output", required=True, help="directory to write results into")
    ap.add_argument("--workers", type=int, default=1, help="parallel tickets (default 1; free tiers rate-limit)")
    ap.add_argument("--no-cache", action="store_true", help="ignore the model-response cache (use for headline runs)")
    ap.add_argument("--no-llm", action="store_true", help="run without the model (template answers only)")
    ap.add_argument("--judge", type=int, default=25, help="LLM-judge sample size for quality proxy (0 to skip)")
    ap.add_argument("--limit", type=int, default=0, help="only the first N tickets (debugging)")
    ap.add_argument("--truth", default=str(config.DATA_DIR / "ground_truth_responses.json"))
    ap.add_argument("--db", default=str(config.DB_PATH))
    a = ap.parse_args(argv)
    logging.basicConfig(level=config.LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for noisy in ("httpx", "httpcore", "sentence_transformers", "chromadb", "urllib3", "huggingface_hub"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    out_dir = Path(a.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        tickets = load_tickets(Path(a.input))
    except Exception as e:
        print(f"ERROR: cannot read input {a.input}: {e}", file=sys.stderr)
        return 2
    if a.limit:
        tickets = tickets[:a.limit]
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:4]
    llm = LLMClient(use_cache=not a.no_cache, enabled=False if a.no_llm else None)
    pipe = SupportPipeline(llm=llm, decision_log=DecisionLog(Path(a.db)))
    t_start = time.time()
    print(f"[{run_id}] processing {len(tickets)} tickets from {a.input} (backend={pipe.retriever.backend}, llm={'off' if a.no_llm else llm.model})", flush=True)

    def one(raw):
        try:
            return pipe.process(raw, run_id=run_id, use_llm=not a.no_llm)
        except Exception as e:   # belt and braces: process() should never raise
            log.exception("unhandled failure")
            return {"ticket_id": str((raw or {}).get("ticket_id", "?")) if isinstance(raw, dict) else "?", "action": "escalate",
                    "route_action": "escalate", "intent": None, "urgency": None, "confidence": None, "sources": [],
                    "response": None, "guardrails": {}, "reason": f"unhandled {type(e).__name__}", "degraded": ["error_harness"],
                    "latency_s": 0.0, "error": type(e).__name__}

    results = []
    if a.workers > 1:
        with ThreadPoolExecutor(a.workers) as ex:
            for i, r in enumerate(ex.map(one, tickets), 1):
                results.append(r)
                if i % 20 == 0:
                    print(f"  {i}/{len(tickets)}", flush=True)
    else:
        for i, raw in enumerate(tickets, 1):
            results.append(one(raw))
            if i % 20 == 0 or i == len(tickets):
                print(f"  {i}/{len(tickets)}", flush=True)
    wall = time.time() - t_start

    reconcile = pipe.dlog.reconcile(run_id, len(results))
    truth = load_truth(Path(a.truth))
    judge = run_judge(results, tickets, truth, pipe.retriever, llm, a.judge) if a.judge and not a.no_llm else None
    meta = {"run_id": run_id, "input": str(a.input), "started_utc": datetime.fromtimestamp(t_start, timezone.utc).isoformat(),
            "wall_clock_seconds": round(wall, 1), "system_version": config.SYSTEM_VERSION, "model": llm.model if not a.no_llm else "none",
            "retrieval_backend": pipe.retriever.backend, "chunk_strategy": pipe.retriever.strategy,
            "confidence_threshold": config.CONFIDENCE_THRESHOLD, "answerable_threshold": config.ANSWERABLE_THRESHOLD,
            "retrieval_min_score": pipe.retriever.min_score, "llm_stats": llm.stats, "cache_used": not a.no_cache}
    M = report_metrics.compute(results, tickets, truth, judge, reconcile, meta)
    M["targets_table"] = report_metrics.targets_table(M)

    (out_dir / "results.jsonl").write_text("\n".join(json.dumps(r, default=str) for r in results))
    (out_dir / "metrics.json").write_text(json.dumps(M, indent=2, default=str))
    (out_dir / "metrics_report.md").write_text(render_md(M))
    with open(out_dir / "decisions.csv", "w", newline="") as f:
        rows = pipe.dlog.rows(run_id)
        if rows:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
    write_review_sheet(out_dir / "review_sample.csv", results, tickets)
    print(f"[{run_id}] done in {wall:.0f}s -> {out_dir}  | auto={M['volume']['answered_automatically']} "
          f"escalated={M['volume']['escalated']} blocked={M['volume']['blocked_by_guardrails']} "
          f"| log reconciles: {reconcile['reconciles']}", flush=True)
    return 0


def write_review_sheet(path: Path, results, tickets, n=50, seed=7):
    by = {t.get("ticket_id"): t for t in tickets if isinstance(t, dict)}
    sent = [r for r in results if r["action"] == "auto_respond"]
    random.Random(seed).shuffle(sent)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ticket_id", "customer_message", "system_response", "cited_passages", "assessor1_unsupported_claim(y/n)", "assessor2_unsupported_claim(y/n)", "notes"])
        for r in sent[:n]:
            t = by.get(r["ticket_id"], {})
            w.writerow([r["ticket_id"], t.get("body", ""), r["response"], "|".join(r.get("cited_passages", [])), "", "", ""])


def render_md(M) -> str:
    v, b, t, g = M["volume"], M["business"], M["technical"], M["governance"]
    L = [f"# Metrics report - run {M['meta']['run_id']}", "",
         f"Input: `{M['meta']['input']}` | model: {M['meta']['model']} | retrieval: {M['meta']['retrieval_backend']}/{M['meta']['chunk_strategy']} "
         f"| wall clock: {M['meta']['wall_clock_seconds']} s | cache used: {M['meta']['cache_used']}", "",
         "## Volume", "", "| Measure | Value |", "|---|---|"]
    L += [f"| {k.replace('_', ' ')} | {val} |" for k, val in v.items()]
    L += ["", "## Business", "", "| Measure | Value |", "|---|---|",
          f"| First contact resolution (proxy) | {b['first_contact_resolution_pct']}% |",
          f"| First contact resolution (verified against labels) | {b.get('first_contact_resolution_verified_pct', 'n/a')}% |",
          f"| Escalation rate | {b['escalation_rate_pct']}% |",
          f"| Reply time, all tickets (mean / median / p95, s) | {b['reply_time_seconds_all_tickets']['mean']} / {b['reply_time_seconds_all_tickets']['median']} / {b['reply_time_seconds_all_tickets']['p95']} |"]
    if "baseline_from_history" in b:
        h = b["baseline_from_history"]
        L.append(f"| Historical baseline (FCR / escalation / median resolution min / CSAT) | {h['first_contact_resolution_pct']}% / {h['escalation_rate_pct']}% / {h['resolution_minutes_median']} / {h['csat_mean']} |")
    if "satisfaction_proxy" in b:
        L.append(f"| Satisfaction proxy (LLM judge, n={b['satisfaction_proxy']['sample_size']}) | {b['satisfaction_proxy']['mean_helpfulness_1_to_5']} / 5 |")
    L += ["", f"_{b['reply_time_note']}_", "", "## Technical", ""]
    if "intent_classification" in t:
        ic = t["intent_classification"]
        L += [f"Intent accuracy {ic['accuracy']:.3f}; weighted precision {ic['precision_weighted']:.3f}; macro recall {ic['recall_macro']:.3f} (n={ic['n']}).", "",
              "| Intent | Precision | Recall | F1 | Support |", "|---|---|---|---|---|"]
        L += [f"| {c} | {d['precision']} | {d['recall']} | {d['f1']} | {d['support']} |" for c, d in ic["per_class"].items()]
        L += ["", f"Urgency accuracy: {t['urgency']['accuracy']}. Calibration ECE: {t['calibration']['expected_calibration_error_points']} points.", "",
              "| Confidence band | n | Stated | Observed | Gap (pts) |", "|---|---|---|---|---|"]
        L += [f"| {r['band']} | {r['n']} | {r['stated_confidence']} | {r['observed_accuracy']} | {r['gap_points']} |" for r in t["calibration"]["bands"]]
        L += ["", f"Retrieval hit rate: {t['retrieval']['hit_rate_pct']}% (n={t['retrieval']['n_answerable_with_docs']}). Routing: {t['routing']}", "",
              f"Citations: {t['citations']}", "", f"Reference-answer checks: {t.get('reference_answers')}", ""]
    L += [f"Latency (s): {t['latency_seconds']}", "", f"Hallucination: {t['hallucination']}", "",
          "## Governance", "", f"- Decisions logged: {g['decisions_logged']} | reconciliation: {g['decision_log_reconciliation']}",
          f"- Guardrail activations: {g['guardrail_activations_by_type']}", f"- Private-data detections (blocked): {g['private_data_detections_blocked']}",
          f"- Private data in outbound responses: {g['private_data_in_outbound_responses']}",
          f"- must_not_auto_respond violations: {g['must_not_auto_respond_violations']}", "", "## Fairness segments", ""]
    for name, tab in M["fairness"].items():
        L += [f"**{name}**", "", "| Segment | n | Auto-answer % | Resolution % | Citation % | Intent acc % | Gap (resolution) |", "|---|---|---|---|---|---|---|"]
        L += [f"| {x['segment']} | {x['n']} | {x['auto_answer_rate_pct']} | {x['resolution_rate_pct']} | {x['citation_accuracy_pct']} | {x['intent_accuracy_pct']} | {x['gap_resolution_rate_pct']} |" for x in tab]
        L.append("")
    L += ["## Targets", "", "| Measure | Baseline | Target | Achieved |", "|---|---|---|---|"]
    L += [f"| {r['measure']} | {r['baseline']} | {r['target']} | {r['achieved']} |" for r in M["targets_table"]]
    return "\n".join(L)


if __name__ == "__main__":
    sys.exit(main())
