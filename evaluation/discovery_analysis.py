"""Computes every Stage-1 discovery figure from the development tickets (nothing typed by hand).
Writes docs/data_findings.json. Usage: python -m evaluation.discovery_analysis"""
import json
import statistics as S
from collections import Counter, defaultdict

from src import config

dev = json.loads((config.DATA_DIR / "development_tickets.json").read_text())
docs = json.loads((config.DATA_DIR / "documentation.json").read_text())


def m(x):
    x = list(x)
    return round(S.mean(x), 3) if x else None


def seg(key):
    g = defaultdict(list)
    for t in dev:
        g[key(t)].append(t)
    return {k: {"n": len(v), "fcr": m(t["history"]["first_contact_resolution"] for t in v),
                "escalated": m(t["history"]["escalated"] for t in v),
                "csat": m(t["history"]["csat_rating"] for t in v if t["history"]["csat_rating"]),
                "median_resolution_min": S.median(t["history"]["resolution_time_minutes"] for t in v),
                "repeat": m(t["history"]["repeat_contact"] for t in v),
                "answerable": m(t["labels"]["answerable_from_docs"] for t in v)} for k, v in sorted(g.items())}


L = lambda t: t["labels"]
out = {"n": len(dev), "channels": dict(Counter(t["channel"] for t in dev)), "urgency": dict(Counter(L(t)["urgency"] for t in dev)),
       "intents": Counter(L(t)["intent"] for t in dev).most_common(),
       "fcr": m(t["history"]["first_contact_resolution"] for t in dev), "escalated": m(t["history"]["escalated"] for t in dev),
       "csat_mean": m(t["history"]["csat_rating"] for t in dev if t["history"]["csat_rating"]),
       "median_resolution_min": S.median(t["history"]["resolution_time_minutes"] for t in dev),
       "mean_resolution_min": round(S.mean(t["history"]["resolution_time_minutes"] for t in dev), 1),
       "repeat_rate": m(t["history"]["repeat_contact"] for t in dev),
       "answerable_share": m(L(t)["answerable_from_docs"] for t in dev),
       "must_not_auto_share": m(L(t)["must_not_auto_respond"] for t in dev),
       "expected_auto_share": m(L(t)["expected_route"] == "auto_respond" for t in dev),
       "non_fluent_share": m(t["language_fluency"] == "non_fluent" for t in dev),
       "by_fluency": seg(lambda t: t["language_fluency"]), "by_tier": seg(lambda t: t["customer_tier"]),
       "by_channel": seg(lambda t: t["channel"]), "by_region": seg(lambda t: t["customer_region"]),
       "by_urgency": seg(lambda t: L(t)["urgency"]), "by_intent": seg(lambda t: L(t)["intent"])}
ans = [t for t in dev if L(t)["answerable_from_docs"]]
out["answerable_but_historically_escalated"] = m(t["history"]["escalated"] for t in ans)
out["answerable_count"] = len(ans)
out["answerable_escalated_count"] = sum(t["history"]["escalated"] for t in ans)
out["escalations_total"] = sum(t["history"]["escalated"] for t in dev)
out["share_of_escalations_that_were_answerable"] = round(out["answerable_escalated_count"] / out["escalations_total"], 3)
# effort: share of volume vs share of total resolution minutes, per intent
tot_min = sum(t["history"]["resolution_time_minutes"] for t in dev)
eff = defaultdict(lambda: [0, 0])
for t in dev:
    eff[L(t)["intent"]][0] += 1
    eff[L(t)["intent"]][1] += t["history"]["resolution_time_minutes"]
out["effort_by_intent"] = sorted([{"intent": k, "volume_share": round(v[0] / len(dev), 3), "effort_share": round(v[1] / tot_min, 3)} for k, v in eff.items()],
                                 key=lambda r: -r["effort_share"])
# label consistency
g = defaultdict(list)
for t in dev:
    g[t["body"]].append((L(t)["answerable_from_docs"], L(t)["expected_route"]))
multi = [v for v in g.values() if len(v) > 1]
out["duplicate_text_groups"] = len(multi)
out["duplicate_groups_with_conflicting_route_labels"] = sum(len(set(v)) > 1 for v in multi)
out["unique_texts"] = len(g)
cov = [t for t in dev if L(t)["intent"] not in config.MUST_ESCALATE_INTENTS]
out["doc_covered_intents_not_answerable_share"] = round(1 - m(L(t)["answerable_from_docs"] for t in cov), 3)
# disagreements between interviewees
out["disagreements"] = {
    "marcus_fcr_42_vs_data": out["fcr"], "marcus_escalation_58_vs_data": out["escalated"],
    "sofia_nonfluent_worst_csat": {"non_fluent": out["by_fluency"]["non_fluent"]["csat"], "fluent": out["by_fluency"]["fluent"]["csat"]},
    "sofia_seven_in_ten_seen_before_vs_answerable": out["answerable_share"],
    "daniel_half_of_escalations_resolvable": out["share_of_escalations_that_were_answerable"],
    "ravi_enterprise_answers_faster": {k: v["median_resolution_min"] for k, v in out["by_tier"].items()},
}
out["articles"] = len(docs)
(config.ROOT / "docs" / "data_findings.json").write_text(json.dumps(out, indent=2))
print(json.dumps({k: out[k] for k in ("fcr", "escalated", "csat_mean", "answerable_share", "answerable_but_historically_escalated",
      "share_of_escalations_that_were_answerable", "duplicate_text_groups", "duplicate_groups_with_conflicting_route_labels", "unique_texts", "doc_covered_intents_not_answerable_share", "disagreements")}, indent=2, default=str))
print(out["effort_by_intent"][:6]); print(out["by_tier"]); print(out["by_fluency"]); print(out["by_channel"])
