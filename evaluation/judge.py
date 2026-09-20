"""LLM-as-judge quality proxy (prompt PR-03). Sampled, cached, and skipped gracefully if the model is unavailable.
This is a PROXY for satisfaction and hallucination rate; the report states its limits."""
from __future__ import annotations

import json
import random
import re

from src.prompts import load_prompt


def run_judge(results, tickets, truth, retriever, llm, n: int, seed: int = 11):
    by = {t.get("ticket_id"): t for t in tickets if isinstance(t, dict)}
    sent = [r for r in results if r["action"] == "auto_respond" and r.get("response")]
    random.Random(seed).shuffle(sent)
    label, system = load_prompt("evaluation/PR-03_response_quality_judge.md")
    scores, unsup, done = [], 0, 0
    for r in sent[:n]:
        t = by.get(r["ticket_id"], {})
        docs = "\n".join(p.text for pid in r.get("cited_passages", []) if (p := retriever.resolve(pid)))
        ref = (truth.get(r["ticket_id"]) or {}).get("reference_response", "")
        user = (f"<ticket>{(t.get('subject') or '')} {t.get('body', '')}</ticket>\n<response>{r['response']}</response>\n"
                f"DOCS:\n{docs}\nREFERENCE ANSWER:\n{ref or '(none)'}")
        res = llm.chat([{"role": "system", "content": system}, {"role": "user", "content": user}], json_mode=True, max_tokens=200)
        if not res.ok:
            continue
        m = re.search(r"\{.*\}", res.text, re.S)
        try:
            d = json.loads(m.group(0))
            scores.append(float(d["helpfulness"]))
            unsup += bool(d.get("unsupported_claim"))
            done += 1
        except Exception:
            continue
    if not done:
        return None
    return {"n": done, "helpfulness_mean": round(sum(scores) / done, 2), "unsupported_rate_pct": round(100 * unsup / done, 2)}
