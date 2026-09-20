"""FR-06 Validate: guardrails that run on every response and can BLOCK (A7).

Guardrail            | Blocks when                                                  | Requirement
---------------------|--------------------------------------------------------------|------------
instruction_integrity| ticket text tries to override instructions / leak the prompt | NFR-04, R-03
pii                  | response contains emails, phones, keys, cards, customer ids, | NFR-04, R-02
                     | or a known customer's full name                              |
grounding            | a sentence lacks a citation resolving to retrieved passages, | FR-05, R-01
                     | or is not lexically supported by what it cites               |
tone_scope           | response makes commitments (refund, credit, fix, dates)      | FR-06, R-01
confidence_floor     | routing confidence missing or below the threshold            | FR-05

A guardrail that fires never redacts-and-sends: the ticket is escalated with the reason.
There is deliberately no switch to disable them.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Iterable, Optional

from . import config

# ------------------------------------------------------------------ patterns
_INJECTION = [
    r"ignore (all |any |the |your |previous |prior |above |earlier )+(instruction|rule|prompt|direction)s?",
    r"disregard (all |any |the |your |previous |prior |above )*(instruction|rule|prompt|direction)s?",
    r"forget (all |your |the |previous )*(instruction|rule|prompt)s?",
    r"(reveal|show|print|repeat|output|leak) (me )?(your |the )?(system |hidden |initial )?(prompt|instruction)s?",
    r"you are now\b", r"\bact as (an? )?(?!customer)", r"pretend (to be|you are)",
    r"\bdeveloper mode\b", r"\bjailbreak\b", r"\bDAN\b", r"new instructions?:",
    r"override (the |your )?(rule|polic|instruction|guardrail|safety)",
    r"</?(ticket|system|assistant)>", r"^\s*system\s*:", r"\bsudo\b.*\bmode\b",
]
_INJ_RE = re.compile("|".join(_INJECTION), re.I | re.M)

_PII = {
    "email": re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
    "phone": re.compile(r"(?<!\w)(?:\+?\d{1,3}[\s.-]?)?(?:\(\d{2,4}\)[\s.-]?)?\d{3,4}[\s.-]\d{3,4}[\s.-]?\d{0,4}(?!\w)"),
    "api_key": re.compile(r"\b(?:sk|pk|rk|ghp|gho|xox[bap]|AKIA|AIza)[-_A-Za-z0-9]{10,}\b|\b[A-Za-z0-9+/_-]{32,}\b"),
    "card": re.compile(r"\b(?:\d[ -]?){13,16}\b"),
    "customer_id": re.compile(r"\bCUST-\d+\b", re.I),
    "ip_address": re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b"),
}
_COMMIT = re.compile(
    r"\b(we|our team)\s+(have|has|will|'ll|are going to|shall|can)\s+(also\s+)?"
    r"(refund|credit|reimburse|waive|issue|fix|resolve|ship|deploy|escalate to|restore|compensate)"
    r"|\brefund(ed)?\b.{0,25}\b(issued|processed|approved|granted|will be)"
    r"|\b(fixed|resolved|corrected) on our (side|end)\b|\bguarantee[sd]?\b|\bwe promise\b|\bI promise\b"
    r"|\b(within|by|in) (\d+|one|two|three|four|five|ten|twenty) (business )?(minute|hour|day|week)s?\b.{0,30}\b(we|will|fix|resolve|respond)"
    r"|\bwill be (fixed|resolved|deployed|completed|restored)\b|\b(eta|deadline)\b|\bcompensation\b",
    re.I)
_STOP = set("a an the and or of to in on for with by at from as is are was were be been it its this that these those "
            "you your we our can will may if then when where which who what how not no do does did have has had "
            "so but also any all please should would could there their them they i my me".split())
_TOK = re.compile(r"[a-z0-9_`./:-]+")


@dataclass
class GuardResult:
    name: str
    passed: bool
    detail: str = ""

    def to_dict(self):
        return {"result": "pass" if self.passed else "block", "detail": self.detail}


@dataclass
class GuardReport:
    results: list[GuardResult] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return any(not r.passed for r in self.results)

    @property
    def failed(self) -> list[GuardResult]:
        return [r for r in self.results if not r.passed]

    def as_dict(self) -> dict:
        return {r.name: r.to_dict() for r in self.results}

    def reason(self) -> str:
        return "; ".join(f"{r.name}: {r.detail}" for r in self.failed)


@lru_cache(maxsize=1)
def known_customer_names() -> frozenset:
    names = set()
    for f in ("development_tickets.json", "validation_tickets.json"):
        p = config.DATA_DIR / f
        if p.exists():
            try:
                names |= {t.get("customer_name", "") for t in json.loads(p.read_text())}
            except Exception:
                pass
    return frozenset(n for n in names if n and " " in n)


# ------------------------------------------------------------------ checks
def instruction_integrity(ticket_text: str) -> GuardResult:
    m = _INJ_RE.search(ticket_text or "")
    if m:
        return GuardResult("instruction_integrity", False, f"ticket contains instruction-override pattern '{m.group(0)[:40]}'")
    return GuardResult("instruction_integrity", True)


def pii(response: str, allowed_text: str = "", extra_names: Iterable[str] = ()) -> GuardResult:
    allowed = (allowed_text or "").lower()
    for kind, rx in _PII.items():
        for m in rx.finditer(response or ""):
            s = m.group(0)
            if s.lower() in allowed:      # e.g. a doc example that legitimately appears in the corpus
                continue
            if kind == "phone" and sum(c.isdigit() for c in s) < 8:
                continue
            if kind == "card" and sum(c.isdigit() for c in s) < 13:
                continue
            return GuardResult("pii", False, f"{kind} detected in response")
    low = (response or "").lower()
    for n in list(known_customer_names()) + list(extra_names):
        if n and n.lower() in low:
            return GuardResult("pii", False, "customer name detected in response")
    return GuardResult("pii", True)


def _content_tokens(s: str) -> list[str]:
    return [t.rstrip(".,:;") for t in _TOK.findall(s.lower()) if t not in _STOP and len(t) > 2]


def _stem(t: str) -> str:
    for suf in ("ing", "ed", "es", "s"):
        if t.endswith(suf) and len(t) - len(suf) >= 4:
            return t[: -len(suf)]
    return t


def grounding(sentences: list[dict], passages_by_id: dict, min_overlap: float = 0.40) -> GuardResult:
    """Each sentence: {"text", "sources": [passage ids]}. Sources must resolve to *retrieved* passages
    (A6) and the sentence must be lexically supported by them (proxy for unsupported claims)."""
    if not sentences:
        return GuardResult("grounding", False, "no answer sentences to ground")
    for i, s in enumerate(sentences):
        srcs = s.get("sources") or []
        if not srcs:
            return GuardResult("grounding", False, f"sentence {i+1} has no citation: '{s.get('text','')[:60]}'")
        bad = [x for x in srcs if x not in passages_by_id]
        if bad:
            return GuardResult("grounding", False, f"sentence {i+1} cites {bad[0]}, which was not retrieved")
        # support is judged against the whole cited article (as retrieved), because a model often cites the
        # neighbouring section of the right article; the citation itself must still resolve to a retrieved passage.
        cited_docs = {passages_by_id[x].doc_id for x in srcs}
        src_text = " ".join(p.text for p in passages_by_id.values() if p.doc_id in cited_docs).lower()
        src_tokens = {_stem(t) for t in _content_tokens(src_text)}
        clean = re.sub(r"DOC-[A-Z]+-\d+(::[\w-]+)?", " ", s.get("text", ""))
        toks = [_stem(t) for t in _content_tokens(clean)]
        if len(toks) >= 5:   # very short sentences carry too few content words for an overlap ratio to mean anything
            overlap = sum(t in src_tokens for t in toks) / len(toks)
            if overlap < min_overlap:
                return GuardResult("grounding", False,
                                   f"sentence {i+1} only {overlap:.0%} supported by cited article: '{s['text'][:60]}'")
        elif toks and not any(t in src_tokens for t in toks):
            return GuardResult("grounding", False, f"sentence {i+1} shares no content words with cited article: '{s['text'][:60]}'")
        nums = [n for n in re.findall(r"\b\d+\b", clean) if n not in ("1", "2", "3", "4", "5", "6", "7", "8", "9")]
        for n in nums:
            if n not in src_text:
                return GuardResult("grounding", False, f"sentence {i+1} states number {n} absent from cited article")
    return GuardResult("grounding", True)


def tone_scope(response: str, allowed_text: str = "") -> GuardResult:
    m = _COMMIT.search(response or "")
    if m:
        return GuardResult("tone_scope", False, f"commitment or promise detected: '{m.group(0)[:50]}'")
    return GuardResult("tone_scope", True)


def confidence_floor(confidence: Optional[float], threshold: float) -> GuardResult:
    if confidence is None or confidence != confidence:
        return GuardResult("confidence_floor", False, "confidence missing: treated as low, not high")
    if confidence < threshold:
        return GuardResult("confidence_floor", False, f"confidence {confidence:.2f} < threshold {threshold:.2f}")
    return GuardResult("confidence_floor", True)


def check_input(ticket_text: str) -> GuardReport:
    return GuardReport([instruction_integrity(ticket_text)])


def check_response(response: str, sentences: list[dict], passages_by_id: dict, confidence: Optional[float],
                   threshold: float, ticket_text: str = "") -> GuardReport:
    allowed = " ".join(p.text for p in passages_by_id.values())
    return GuardReport([
        instruction_integrity(ticket_text),
        pii(response, allowed),
        grounding(sentences, passages_by_id),
        tone_scope(response, allowed),
        confidence_floor(confidence, threshold),
    ])
