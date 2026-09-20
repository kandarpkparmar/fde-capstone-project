"""Computes every figure the Build Specification requires, from the run results (A10). No hand work.

Groups: Volume | Business | Technical | Governance (+ fairness segments, calibration, confusion matrix).
Label-dependent figures are skipped (and marked 'n/a') if the input file has no labels.
"""
from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from typing import Optional

import numpy as np

from src import guardrails


def _pct(x, n):
    return round(100.0 * x / n, 2) if n else None


def _q(vals, q):
    return round(float(np.percentile(vals, q)), 4) if vals else None


def _stats(vals):
    if not vals:
        return {"mean": None, "median": None, "p95": None, "n": 0}
    return {"mean": round(statistics.mean(vals), 4), "median": round(statistics.median(vals), 4),
            "p95": _q(vals, 95), "n": len(vals)}


def calibration(conf, correct, bins=5):
    rows, ece, n = [], 0.0, len(conf)
    for i in range(bins):
        lo, hi = i / bins, (i + 1) / bins
        idx = [j for j, c in enumerate(conf) if lo <= c < hi or (i == bins - 1 and c == 1.0)]
        if not idx:
            continue
        stated = float(np.mean([conf[j] for j in idx]))
        obs = float(np.mean([correct[j] for j in idx]))
        rows.append({"band": f"{lo:.1f}-{hi:.1f}", "n": len(idx), "stated_confidence": round(stated, 4),
                     "observed_accuracy": round(obs, 4), "gap_points": round(100 * (stated - obs), 2)})
        ece += len(idx) / n * abs(stated - obs)
    return rows, round(100 * ece, 2)


def length_bucket(text: str) -> str:
    return "short (<100 chars)" if len(text or "") < 100 else "long (>=100 chars)"


def compute(results: list[dict], tickets: list[dict], truth_by_id: Optional[dict] = None, judge: Optional[dict] = None,
            reconcile: Optional[dict] = None, run_meta: Optional[dict] = None) -> dict:
    truth_by_id = truth_by_id or {}
    n = len(results)
    by_id = {t.get("ticket_id"): t for t in tickets if isinstance(t, dict)}
    rows = []                              # joined result + ticket
    for r in results:
        t = by_id.get(r["ticket_id"], {}) if isinstance(by_id.get(r["ticket_id"], {}), dict) else {}
        rows.append((r, t, t.get("labels") or {}))
    labelled = [x for x in rows if x[2].get("intent")]
    act = Counter(r["action"] for r in results)
    M: dict = {"meta": run_meta or {}}

    # ---------------- volume
    M["volume"] = {"tickets_processed": n, "answered_automatically": act["auto_respond"],
                   "escalated": act["escalate"], "blocked_by_guardrails": act["block"],
                   "degraded_llm_fallback": sum("llm_fallback_template" in r["degraded"] for r in results),
                   "degraded_retrieval_fallback": sum("retrieval_tfidf_fallback" in r["degraded"] for r in results),
                   "stage_errors": sum(bool(r.get("error")) for r in results)}

    # ---------------- business
    lat = [r["latency_s"] for r in results]
    auto_lat = [r["latency_s"] for r in results if r["action"] == "auto_respond"]
    fcr = _pct(act["auto_respond"], n)
    esc_rate = _pct(act["escalate"] + act["block"], n)
    hist = [x[1].get("history") for x in rows if x[1].get("history")]
    B = {"first_contact_resolution_pct": fcr,
         "escalation_rate_pct": esc_rate,
         "reply_time_seconds_all_tickets": _stats(lat),
         "reply_time_seconds_auto_answers": _stats(auto_lat),
         "reply_time_note": "First reply = answer or acknowledgement produced by the system. Time a human then takes on escalated tickets is NOT simulated.",
         "repeat_contacts": "not measurable: needs live customer follow-up data"}
    if labelled:
        verified = sum(1 for r, t, l in labelled if r["action"] == "auto_respond" and l.get("expected_route") == "auto_respond")
        B["first_contact_resolution_verified_pct"] = _pct(verified, len(labelled))
        B["fcr_note"] = ("Headline FCR counts an automatic answer as resolved (proxy: no live customer to confirm). "
                         "'Verified' counts it only if the reference label also says auto_respond.")
    if hist:
        B["baseline_from_history"] = {
            "n": len(hist),
            "first_contact_resolution_pct": _pct(sum(bool(h.get("first_contact_resolution")) for h in hist), len(hist)),
            "escalation_rate_pct": _pct(sum(bool(h.get("escalated")) for h in hist), len(hist)),
            "resolution_minutes_mean": round(statistics.mean(h["resolution_time_minutes"] for h in hist if h.get("resolution_time_minutes") is not None), 1),
            "resolution_minutes_median": round(statistics.median(h["resolution_time_minutes"] for h in hist if h.get("resolution_time_minutes") is not None), 1),
            "csat_mean": round(statistics.mean(h["csat_rating"] for h in hist if h.get("csat_rating")), 2)}
    if judge and judge.get("n"):
        B["satisfaction_proxy"] = {"mean_helpfulness_1_to_5": judge["helpfulness_mean"], "sample_size": judge["n"],
                                   "method": "LLM judge (prompt PR-03) against senior-agent reference; NOT human raters; proxy only"}
    M["business"] = B

    # ---------------- technical
    T: dict = {"latency_seconds": {"mean": _stats(lat)["mean"], "median": _stats(lat)["median"], "p95": _stats(lat)["p95"]}}
    if labelled:
        y = [l["intent"] for _, _, l in labelled]
        p = [r["intent"] for r, _, _ in labelled]
        classes = sorted(set(y) | set(p))
        per = {}
        for c in classes:
            tp = sum(a == c and b == c for a, b in zip(y, p))
            fp = sum(a != c and b == c for a, b in zip(y, p))
            fn = sum(a == c and b != c for a, b in zip(y, p))
            pr = tp / (tp + fp) if tp + fp else None
            rc = tp / (tp + fn) if tp + fn else None
            f1 = 2 * pr * rc / (pr + rc) if pr and rc else (0.0 if (pr is not None and rc is not None) else None)
            per[c] = {"precision": None if pr is None else round(pr, 4), "recall": None if rc is None else round(rc, 4),
                      "f1": None if f1 is None else round(f1, 4), "support": y.count(c)}
        acc = sum(a == b for a, b in zip(y, p)) / len(y)
        sup = [per[c]["support"] for c in classes if per[c]["precision"] is not None]
        prec_w = sum(per[c]["precision"] * per[c]["support"] for c in classes if per[c]["precision"] is not None) / max(sum(sup), 1)
        T["intent_classification"] = {"accuracy": round(acc, 4), "precision_weighted": round(prec_w, 4),
                                      "precision_macro": round(float(np.mean([v["precision"] for v in per.values() if v["precision"] is not None])), 4),
                                      "recall_macro": round(float(np.mean([v["recall"] for v in per.values() if v["recall"] is not None])), 4),
                                      "per_class": per, "n": len(y)}
        cm = defaultdict(Counter)
        for a, b in zip(y, p):
            cm[a][b] += 1
        T["confusion_matrix"] = {a: dict(b) for a, b in cm.items()}
        uy = [l["urgency"] for _, _, l in labelled if l.get("urgency")]
        up = [r["urgency"] for r, _, l in labelled if l.get("urgency")]
        T["urgency"] = {"accuracy": round(sum(a == b for a, b in zip(uy, up)) / max(len(uy), 1), 4),
                        "per_class": {c: {"precision": round(sum(a == c and b == c for a, b in zip(uy, up)) / max(up.count(c), 1), 4),
                                          "recall": round(sum(a == c and b == c for a, b in zip(uy, up)) / max(uy.count(c), 1), 4),
                                          "support": uy.count(c)} for c in sorted(set(uy))}}
        rows_cal, ece = calibration([r["confidence"] or 0 for r, _, _ in labelled], [a == b for a, b in zip(y, p)])
        T["calibration"] = {"bands": rows_cal, "expected_calibration_error_points": ece}
        # retrieval
        ans = [(r, l) for r, _, l in labelled if l.get("answerable_from_docs") and l.get("expected_doc_ids")]
        hit_any = sum(bool({s["doc_id"] for s in r["sources"]} & set(l["expected_doc_ids"])) for r, l in ans)
        unans = [(r, l) for r, _, l in labelled if not l.get("answerable_from_docs")]
        T["retrieval"] = {"hit_rate_pct": _pct(hit_any, len(ans)), "n_answerable_with_docs": len(ans),
                          "correctly_empty_for_unanswerable_pct": _pct(sum(not r["sources"] for r, _ in unans), len(unans)),
                          "note": "hit = any expected doc among retrieved passages. Unanswerable tickets often still retrieve loosely related passages; routing/generation are the safeguards."}
        # routing
        route_ok = sum((r["route_action"] or "escalate") == l.get("expected_route") for r, _, l in labelled)
        auto_r = [(r, l) for r, _, l in labelled if r["action"] == "auto_respond"]
        T["routing"] = {"accuracy_pct": _pct(route_ok, len(labelled)),
                        "auto_answer_precision_pct": _pct(sum(l.get("expected_route") == "auto_respond" for _, l in auto_r), len(auto_r)),
                        "wrongly_auto_answered": sum(l.get("expected_route") == "escalate" for _, l in auto_r),
                        "missed_automation_pct": _pct(sum(r["action"] != "auto_respond" and l.get("expected_route") == "auto_respond" for r, _, l in labelled),
                                                       sum(l.get("expected_route") == "auto_respond" for _, _, l in labelled)),
                        "note": "Final action vs expected_route label. Includes the labels' irreducible noise (identical tickets carry both labels)."}
        # citations
        sent = [(r, t, l) for r, t, l in labelled if r["action"] == "auto_respond"]
        cit_total = cit_resolves = cit_expected = 0
        for r, t, l in sent:
            passages = {s["passage_id"] for s in r["sources"]}
            for pid in r.get("cited_passages", []):
                cit_total += 1
                cit_resolves += pid in passages
                cit_expected += pid.split("::")[0] in set(l.get("expected_doc_ids", []))
        T["citations"] = {"citations_checked": cit_total,
                          "resolve_to_retrieved_passages_pct": _pct(cit_resolves, cit_total),
                          "cite_an_expected_document_pct": _pct(cit_expected, cit_total),
                          "answers_with_expected_doc_cited_pct": _pct(sum(bool({c.split('::')[0] for c in r.get('cited_passages', [])} & set(l.get('expected_doc_ids', []))) for r, _, l in sent), len(sent))}
        # ground-truth checks
        mm_tot = mm_hit = mnc = gt_n = 0
        for r, t, l in sent:
            g = truth_by_id.get(r["ticket_id"])
            if not g:
                continue
            gt_n += 1
            resp = (r.get("response") or "").lower()
            for m in g.get("must_mention", []):
                mm_tot += 1
                mm_hit += m.lower() in resp
            mnc += sum(c.lower() in resp for c in g.get("must_not_claim", []))
        T["reference_answers"] = {"answers_with_reference": gt_n, "must_mention_coverage_pct": _pct(mm_hit, mm_tot),
                                  "must_not_claim_violations": mnc}
    # hallucination proxy
    drafts_blocked_grounding = sum(1 for r in results if r["guardrails"].get("grounding", {}).get("result") == "block")
    sent_all = [r for r in results if r["action"] == "auto_respond"]
    T["hallucination"] = {"drafts_blocked_for_unsupported_claims": drafts_blocked_grounding,
                          "sent_answers_passing_grounding_check_pct": _pct(sum(r["guardrails"].get("grounding", {}).get("result") == "pass" for r in sent_all), len(sent_all)),
                          "judge_unsupported_claim_rate_pct": judge.get("unsupported_rate_pct") if judge else None,
                          "judge_sample_size": judge.get("n") if judge else 0,
                          "note": "Rate among SENT answers estimated by an LLM judge on a sample; a human review sheet (review_sample.csv) is produced for the required two-assessor check, which this run does not include."}
    M["technical"] = T

    # ---------------- governance
    G = {"decisions_logged": (reconcile or {}).get("decisions_logged"), "decision_log_reconciliation": reconcile,
         "guardrail_activations_by_type": dict(Counter(k for r in results for k, v in r["guardrails"].items() if v.get("result") == "block")),
         "private_data_detections_blocked": sum(r["guardrails"].get("pii", {}).get("result") == "block" for r in results)}
    outbound_pii = 0
    for r in results:
        if r["action"] == "auto_respond":
            allowed = " ".join(s.get("passage_id", "") for s in r["sources"])
            if not guardrails.pii(r["response"] or "", "").passed:
                outbound_pii += 1
    G["private_data_in_outbound_responses"] = outbound_pii
    G["must_not_auto_respond_violations"] = sum(1 for r, _, l in labelled if r["action"] == "auto_respond" and l.get("must_not_auto_respond")) if labelled else "n/a"
    M["governance"] = G

    # ---------------- fairness
    fair = {}
    if labelled:
        segs = {"customer_tier": lambda t: t.get("customer_tier"), "customer_region": lambda t: t.get("customer_region"),
                "language_fluency": lambda t: t.get("language_fluency"), "channel": lambda t: t.get("channel"),
                "ticket_length": lambda t: length_bucket(t.get("body", ""))}
        for name, fn in segs.items():
            groups = defaultdict(list)
            for r, t, l in labelled:
                groups[fn(t)].append((r, t, l))
            tab = []
            for g, items in sorted(groups.items(), key=lambda kv: str(kv[0])):
                k = len(items)
                good = sum(1 for r, _, l in items if r["action"] == "auto_respond" and l.get("expected_route") == "auto_respond")
                res_rate = _pct(good, sum(1 for _, _, l in items if l.get("expected_route") == "auto_respond"))
                sentg = [(r, l) for r, _, l in items if r["action"] == "auto_respond"]
                cit = _pct(sum(bool({c.split("::")[0] for c in r.get("cited_passages", [])} & set(l.get("expected_doc_ids", []))) for r, l in sentg), len(sentg)) if sentg else None
                tab.append({"segment": str(g), "n": k, "auto_answer_rate_pct": _pct(sum(r["action"] == "auto_respond" for r, _, _ in items), k),
                            "resolution_rate_pct": res_rate, "citation_accuracy_pct": cit,
                            "intent_accuracy_pct": _pct(sum(r["intent"] == l["intent"] for r, _, l in items), k),
                            "median_latency_s": round(statistics.median(r["latency_s"] for r, _, _ in items), 3)})
            for key in ("resolution_rate_pct", "citation_accuracy_pct", "intent_accuracy_pct"):
                vals = [x[key] for x in tab if x[key] is not None and x["n"] >= 5]
                best = max(vals) if vals else None
                for x in tab:
                    x["gap_" + key] = round(best - x[key], 2) if (best is not None and x[key] is not None) else None
            fair[name] = tab
    M["fairness"] = fair
    return M


def targets_table(M: dict) -> list[dict]:
    b, t, g = M["business"], M["technical"], M["governance"]
    ic = t.get("intent_classification", {})
    rows = [
        ("First contact resolution", "42%", ">= 60%", f'{b["first_contact_resolution_pct"]}%'),
        ("Escalation rate", "58%", "<= 30%", f'{b["escalation_rate_pct"]}%'),
        ("Mean time to first reply", "8-12 h", "< 5 min", f'{b["reply_time_seconds_all_tickets"]["mean"]} s'),
        ("Median time to first reply", "n/a", "n/a", f'{b["reply_time_seconds_all_tickets"]["median"]} s'),
        ("Intent classification precision (weighted)", "-", ">= 85%", f'{round(100*ic["precision_weighted"],1)}%' if ic else "n/a"),
        ("Citation accuracy (resolves to retrieved passage)", "-", ">= 95%", f'{t.get("citations", {}).get("resolve_to_retrieved_passages_pct", "n/a")}%'),
        ("Latency p95", "-", "< 3 s", f'{t["latency_seconds"]["p95"]} s'),
        ("Private data in outbound responses", "-", "0", str(g["private_data_in_outbound_responses"])),
        ("Decision log reconciles", "-", "exact", str((g.get("decision_log_reconciliation") or {}).get("reconciles"))),
    ]
    return [dict(measure=a, baseline=b_, target=c, achieved=d) for a, b_, c, d in rows]
