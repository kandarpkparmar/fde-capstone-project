"""FR-04 Generate: grounded, cited answers in a defined JSON structure.

* Ticket text is passed as delimited, sanitised data; instructions live only in the system prompt.
* The model must cite passage ids; citations are later verified against the retrieved set (A6).
* If the model is unavailable, times out, or returns unparseable output, we fall back to an
  extractive template built directly from the top retrieved passage: fully grounded by construction.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Optional

from .ingest import Ticket
from .llm import LLMClient
from .prompts import load_prompt
from .retrieve import Passage, Retriever

FOOTER = ("This reply was drafted by an automated assistant from CloudServe documentation. "
          "If it does not resolve your issue, reply to this message and a support engineer will review it.")


@dataclass
class GenResult:
    can_answer: bool
    sentences: list[dict] = field(default_factory=list)
    source: str = "none"          # llm | template | none
    prompt_version: str = ""
    model: str = ""
    latency_s: float = 0.0
    cached: bool = False
    note: str = ""


def _sanitise(s: str) -> str:
    return s.replace("<", "(").replace(">", ")")


def build_messages(ticket: Ticket, passages: list[Passage]) -> list[dict]:
    _, system = load_prompt("build/PR-01_answer_generation.md")
    docs = "\n\n".join(f"[{p.passage_id}] {p.title}\n{p.text}" for p in passages)
    user = (f"<ticket>\nChannel: {ticket.channel}\nSubject: {_sanitise(ticket.subject)}\n"
            f"Message: {_sanitise(ticket.body)}\n</ticket>\n\nDOCUMENTATION PASSAGES:\n{docs}\n\n"
            "Return the JSON now.")
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def parse_output(text: str) -> Optional[dict]:
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except Exception:
        return None
    if not isinstance(d, dict) or "can_answer" not in d:
        return None
    sents = d.get("sentences") or []
    clean = []
    for s in sents if isinstance(sents, list) else []:
        if isinstance(s, dict) and isinstance(s.get("text"), str) and s["text"].strip():
            src = s.get("sources") or []
            src = [src] if isinstance(src, str) else [x for x in src if isinstance(x, str)]
            clean.append({"text": s["text"].strip(), "sources": src})
    return {"can_answer": bool(d["can_answer"]), "sentences": clean}


def template_answer(passages: list[Passage], retriever: Retriever) -> GenResult:
    """Extractive fallback: numbered resolution steps of the top-ranked article, verbatim."""
    if not passages:
        return GenResult(False, note="no passages")
    doc_id = passages[0].doc_id
    p = next((x for x in passages if x.doc_id == doc_id and "resol" in x.section.lower()), None) \
        or retriever.resolve(f"{doc_id}::resolution") or passages[0]
    steps = [m.group(1).strip() for m in re.finditer(r"^\s*\d+\.\s+(.+)$", p.text, re.M)][:5]
    if not steps:
        body = [l.strip("-* ").strip() for l in p.text.splitlines()[1:] if l.strip()][:4]
        steps = body
    if not steps:
        return GenResult(False, note="no extractable steps")
    sents = [{"text": f"Our documentation '{p.title}' suggests the following.", "sources": [p.passage_id]}]
    sents += [{"text": s if s.endswith((".", "!", "?")) else s + ".", "sources": [p.passage_id]} for s in steps]
    return GenResult(True, sents, source="template", note="extractive fallback")


def generate(ticket: Ticket, passages: list[Passage], llm: LLMClient, retriever: Retriever) -> GenResult:
    label, _ = load_prompt("build/PR-01_answer_generation.md")
    res = llm.chat(build_messages(ticket, passages), json_mode=True)
    if not res.ok:
        g = template_answer(passages, retriever)
        g.note = f"LLM unavailable ({res.error}); used extractive template"
        g.prompt_version, g.model, g.latency_s = "template-v1", "none", res.latency_s
        return g
    parsed = parse_output(res.text)
    if parsed is None:
        g = template_answer(passages, retriever)
        g.note = "LLM output not parseable; used extractive template"
        g.prompt_version, g.model, g.latency_s = "template-v1", res.model, res.latency_s
        return g
    return GenResult(parsed["can_answer"] and bool(parsed["sentences"]), parsed["sentences"], source="llm",
                     prompt_version=label, model=res.model, latency_s=res.latency_s, cached=res.cached,
                     note="" if parsed["can_answer"] else "model reported the passages do not answer the question")


def render(sentences: list[dict], retriever: Retriever) -> str:
    """Final customer-facing text: inline [DOC-ID] citations, a source list, and an automation disclosure."""
    parts, cited = [], []
    for s in sentences:
        docs = []
        for sid in s["sources"]:
            p = retriever.resolve(sid)
            d = p.doc_id if p else sid
            if d not in docs:
                docs.append(d)
            if p and p not in cited:
                cited.append(p)
        parts.append(s["text"] + (" [" + ", ".join(docs) + "]" if docs else ""))
    src = "\n".join(f"- {p.doc_id}: {p.title} ({p.section})" for p in cited)
    return "Hello,\n\n" + " ".join(parts) + "\n\nSources:\n" + src + "\n\n" + FOOTER
