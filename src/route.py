"""FR-05 Route: decide auto-respond vs escalate. Pure and deterministic (A5).

The decision depends only on the classification and retrieval outputs (both deterministic) and the
configured thresholds, never on the language model. Every branch produces a human-readable reason.
Thresholds come from data: see evaluation/tune_thresholds.py and docs/decisions/threshold.md.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from . import config
from .classify import Classification


@dataclass(frozen=True)
class RouteDecision:
    action: str                 # auto_respond | escalate
    reason: str
    threshold: float
    rule: str                   # which branch fired (for audit)
    unsure_about: tuple = ()


def decide(cls: Classification, passages: list, kill_switch: bool = False,
           threshold: Optional[float] = None, answerable_threshold: Optional[float] = None,
           intent_docs: Optional[dict] = None) -> RouteDecision:
    T = config.CONFIDENCE_THRESHOLD if threshold is None else threshold
    Ta = config.ANSWERABLE_THRESHOLD if answerable_threshold is None else answerable_threshold
    if kill_switch:
        return RouteDecision("escalate", "Kill switch is on: automatic answering is disabled, all tickets go to a human.", T, "kill_switch")
    if cls.fallback:
        return RouteDecision("escalate", f"Ticket could not be classified ({cls.note or 'no usable text'}), so a person must read it.", T, "classification_fallback", ("classification",))
    if cls.intent in config.MUST_ESCALATE_INTENTS:
        return RouteDecision("escalate", f"'{cls.intent}' tickets are never answered automatically (security, compliance, commitments or no documentation exist for them).", T, "policy_must_escalate", ("policy",))
    if cls.intent_confidence is None or cls.intent_confidence < T:
        return RouteDecision("escalate", f"Classifier confidence {cls.intent_confidence:.2f} is below the {T:.2f} threshold.", T, "low_confidence", ("intent",))
    if not passages:
        return RouteDecision("escalate", "No documentation passage was relevant enough to ground an answer.", T, "no_retrieval_hit", ("documentation",))
    if intent_docs is not None:
        expected = intent_docs.get(cls.intent, set())
        if expected and passages[0].doc_id not in expected:
            return RouteDecision("escalate", f"Top retrieved article {passages[0].doc_id} does not match the usual documentation for '{cls.intent}'.", T, "retrieval_topic_mismatch", ("documentation match",))
    if cls.answerable_prob < Ta:
        return RouteDecision("escalate", f"Estimated chance this is answerable from documentation is {cls.answerable_prob:.2f}, below {Ta:.2f}.", T, "low_answerability", ("answerability",))
    return RouteDecision("auto_respond", f"Intent '{cls.intent}' at confidence {cls.intent_confidence:.2f} (>= {T:.2f}), relevant documentation found ({passages[0].doc_id}, score {passages[0].score:.2f}), answerability {cls.answerable_prob:.2f}.", T, "auto_respond")


def build_escalation_packet(ticket, cls: Classification, passages: list, decision: RouteDecision,
                            draft_note: str = "") -> dict:
    """What a tier-1/tier-2 agent receives: summary, sources, and what the system was unsure about
    (Daniel Okonkwo: 'show its working'; Sofia Restrepo: 'a draft and the relevant page attached')."""
    tier_rank = {"enterprise": 0, "business": 1, "standard": 2}.get(ticket.customer_tier, 2)
    urg = {"high": 0, "medium": 1, "low": 2}.get(cls.urgency, 1)
    prio = "P1" if (urg == 0 and tier_rank <= 1) or cls.intent == "security_incident" else ("P2" if urg <= 1 else "P3")
    alts = ", ".join(f"{a['value']} ({a['confidence']:.2f})" for a in cls.alternatives[:3])
    docs = "; ".join(f"{p.doc_id} '{p.title}' (score {p.score:.2f})" for p in passages[:3]) or "none relevant"
    unsure = list(decision.unsure_about) or ["nothing specific; escalated by policy"]
    summary = (f"{cls.intent.replace('_', ' ').title()} ticket via {ticket.channel}, {cls.urgency} urgency, "
               f"{ticket.customer_tier} customer. Classified with confidence {cls.intent_confidence:.2f}; "
               f"alternatives: {alts or 'n/a'}. Escalated because: {decision.reason} "
               f"Relevant documentation: {docs}. Not confident about: {', '.join(unsure)}.")
    return {
        "priority": prio, "summary": summary, "intent": cls.intent, "urgency": cls.urgency,
        "classifier_confidence": cls.intent_confidence, "alternatives": cls.alternatives,
        "unsure_about": unsure, "reason": decision.reason,
        "sources": [{"doc_id": p.doc_id, "passage_id": p.passage_id, "title": p.title, "score": p.score,
                     "snippet": p.text[:280]} for p in passages[:3]],
        "draft_note": draft_note,
        "original_text": ticket.original_body,
    }


ACK_TEXT = ("Thank you for contacting CloudServe Support. Your request has been passed to a member of our support "
            "team together with a summary and the relevant documentation, so you will not need to repeat yourself. "
            "This acknowledgement was generated automatically.")
