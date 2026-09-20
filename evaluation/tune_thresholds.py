"""Determine the routing thresholds and the calibration temperature FROM DATA (FR-05, decision D-03).

Uses ONLY the development tickets, with out-of-fold predictions (5-fold, grouped by identical ticket
text so templated duplicates cannot leak across folds). Nothing here touches validation or hidden data.

Objective (Marcus Adeyemi: 'I would rather it said nothing than said something wrong'):
maximise  net = correct_auto - C * wrong_auto   subject to zero must_not_auto_respond tickets answered
automatically. A wrong automatic answer is assumed to cost C=3x what a right one earns (a bounced ticket costs
~4x a resolved one per Marcus, and a wrong answer additionally creates a complaint). Sensitivity to C is reported.
A hard precision floor was tried first and found infeasible: ~20% of doc-covered tickets carry answerable=False
labels that cannot be predicted from any available field (see docs/data_findings.md), so precision from text alone
plateaus near 0.75-0.80. The generation step (model can_answer + grounding guardrail) is the second filter.
Usage: python -m evaluation.tune_thresholds
"""
import json
import sys

import numpy as np
from sklearn.model_selection import StratifiedGroupKFold

from src import config, route
from src.classify import TicketClassifier, load_dev
from src.retrieve import Retriever

COST_WRONG = 3.0
TEMPERATURE_CAP = 0.5   # NLL optimum sits on the search boundary because OOF accuracy is 100% on templated text;
                        # capped to avoid over-confidence on out-of-distribution text


def oof_predictions(tickets, labels, seed=0):
    y = [l["intent"] for l in labels]
    groups = [t.text for t in tickets]
    preds = [None] * len(tickets)
    for tr, te in StratifiedGroupKFold(5, shuffle=True, random_state=seed).split(tickets, y, groups):
        m = TicketClassifier().fit([tickets[i] for i in tr], [labels[i] for i in tr])
        for i, c in zip(te, m.predict_batch([tickets[i] for i in te])):
            preds[i] = c
    return preds


def fit_temperature(probs_true, ):
    return None


def main():
    tickets, labels = load_dev()
    preds = oof_predictions(tickets, labels)
    # ---- temperature: minimise NLL of the true class using raw OOF probabilities
    y = [l["intent"] for l in labels]
    groups = [t.text for t in tickets]
    raw_true = []
    for tr, te in StratifiedGroupKFold(5, shuffle=True, random_state=0).split(tickets, y, groups):
        m = TicketClassifier().fit([tickets[i] for i in tr], [labels[i] for i in tr])
        X = [t.text + f" chan_{t.channel}" for t in [tickets[i] for i in te]]
        P = m.intent.proba(X)
        for row, i in zip(P, te):
            raw_true.append((row, m.intent.classes.index(y[i])))
    best = (None, 1e9)
    for T in np.arange(0.2, 1.51, 0.05):
        nll = 0
        for row, k in raw_true:
            z = np.log(np.clip(row, 1e-9, 1)) / T
            z -= z.max()
            p = np.exp(z) / np.exp(z).sum()
            nll -= np.log(max(p[k], 1e-9))
        if nll < best[1]:
            best = (round(float(T), 2), nll)
    temperature = max(best[0], TEMPERATURE_CAP)
    print('nll-optimal temperature', best[0], '-> using', temperature)
    print("temperature", temperature)
    # re-run OOF with temperature applied
    ptemp = []
    for tr, te in StratifiedGroupKFold(5, shuffle=True, random_state=0).split(tickets, y, groups):
        m = TicketClassifier().fit([tickets[i] for i in tr], [labels[i] for i in tr], temperature=temperature)
        for i, c in zip(te, m.predict_batch([tickets[i] for i in te])):
            ptemp.append((i, c))
    preds = [c for _, c in sorted(ptemp, key=lambda x: x[0])]
    retr = Retriever(persist=False)
    passages = [retr.search(t.text) for t in tickets]
    full = TicketClassifier().fit(tickets, labels)
    rows = []
    for T in np.arange(0.5, 0.99, 0.02):
        for Ta in np.arange(0.0, 0.96, 0.05):
            auto = correct_auto = must_viol = 0
            for c, ps, l in zip(preds, passages, labels):
                d = route.decide(c, ps, threshold=float(T), answerable_threshold=float(Ta), intent_docs=full.intent_docs)
                if d.action == "auto_respond":
                    auto += 1
                    correct_auto += l["expected_route"] == "auto_respond"
                    must_viol += bool(l["must_not_auto_respond"])
            rows.append({"T": round(float(T), 2), "Ta": round(float(Ta), 2), "auto": auto, "auto_rate": round(auto / len(labels), 4),
                         "auto_precision": round(correct_auto / auto, 4) if auto else 0, "must_not_violations": must_viol})
    for r in rows:
        r["correct_auto"] = round(r["auto"] * r["auto_precision"])
        r["wrong_auto"] = r["auto"] - r["correct_auto"]
    def net(r, c=COST_WRONG):
        return r["correct_auto"] - c * r["wrong_auto"]
    ok = [r for r in rows if r["must_not_violations"] == 0]
    chosen = max(ok, key=lambda r: (net(r), -abs(r["T"] - 0.80), r["Ta"]))
    sens = {}
    for c in (1, 2, 3, 5):
        b = max(ok, key=lambda r: (net(r, c), -abs(r["T"] - 0.80), r["Ta"]))
        sens[str(c)] = {"T": b["T"], "Ta": b["Ta"], "auto_rate": b["auto_rate"], "auto_precision": b["auto_precision"]}
    print("chosen", chosen)
    # a readable frontier for the report: best auto_rate per Ta (T fixed at chosen)
    frontier = [r for r in rows if r["T"] == chosen["T"]]
    out = {"temperature": temperature, "chosen": chosen, "cost_wrong": COST_WRONG, "sensitivity_to_cost": sens, "n_dev": len(labels),
           "frontier_at_chosen_T": frontier, "method": "5-fold out-of-fold, grouped by identical text"}
    (config.ROOT / "docs" / "threshold_decision.json").write_text(json.dumps(out, indent=2))
    (config.ROOT / "src" / "calibration_defaults.py").write_text(f"# written by evaluation/tune_thresholds.py\nDEFAULT_TEMPERATURE = {temperature}\n")
    print("wrote docs/threshold_decision.json and src/calibration_defaults.py")
    for r in frontier[::2]:
        print(r)


if __name__ == "__main__":
    main()
