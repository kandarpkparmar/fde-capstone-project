"""The end-to-end chain: ingest -> classify -> retrieve -> route -> generate -> validate -> log.

`process()` never raises: any failure in a stage degrades to an escalation with the reason
recorded, and exactly one `outcome` row is always written to the decision log (A8, A11).
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Optional

from . import config, guardrails, metrics, route
from .classify import TicketClassifier, get_classifier
from .generate import generate, render
from .ingest import Ticket, normalise
from .llm import LLMClient
from .logging_store import DecisionLog
from .retrieve import Retriever, top_docs

log = logging.getLogger(__name__)
REQ = {"ingest": ["FR-01"], "classification": ["FR-02"], "retrieval": ["FR-03"], "routing": ["FR-05", "FR-07", "FR-12"],
       "generation": ["FR-04", "FR-09", "FR-14"], "validation": ["FR-06"], "outcome": ["FR-08"]}


def select_for_generation(passages, ratio: float = 0.9):
    """Give the model only the best article's passages (plus another article scoring within 10% of it):
    less noise, fewer tokens, more precise citations."""
    if not passages:
        return []
    top = passages[0].score
    docs = [passages[0].doc_id]
    for p in passages[1:]:
        if p.doc_id not in docs and p.score >= ratio * top:
            docs.append(p.doc_id)
    return [p for p in passages if p.doc_id in docs]


def kill_switch_on() -> bool:
    return config.KILL_SWITCH_FILE.exists()


class SupportPipeline:
    def __init__(self, classifier: Optional[TicketClassifier] = None, retriever: Optional[Retriever] = None,
                 llm: Optional[LLMClient] = None, decision_log: Optional[DecisionLog] = None,
                 intent_docs: Optional[dict] = None):
        self.classifier = classifier or get_classifier()
        self.retriever = retriever or Retriever()
        self.llm = llm or LLMClient()
        self.dlog = decision_log or DecisionLog()
        self.intent_docs = intent_docs if intent_docs is not None else getattr(self.classifier, "intent_docs", None)
        self.model_info = {"name": self.llm.model, "version": config.SYSTEM_VERSION,
                           "classifier": "tfidf-logreg", "retrieval": f"{self.retriever.backend}:{self.retriever.strategy}"}

    # ------------------------------------------------------------------
    def process(self, raw, run_id: Optional[str] = None, use_llm: bool = True) -> dict:
        run_id = run_id or uuid.uuid4().hex[:12]
        t0 = time.perf_counter()
        ticket: Ticket = normalise(raw)
        out = {"ticket_id": ticket.ticket_id, "channel": ticket.channel, "run_id": run_id, "action": "escalate",
               "route_action": None, "intent": None, "urgency": None, "confidence": None, "sources": [],
               "response": None, "escalation_packet": None, "guardrails": {}, "reason": "", "degraded": [],
               "generation_source": "none", "quality_flags": ticket.quality_flags, "error": None}
        stage = "ingest"
        try:
            self._log(run_id, ticket, "ingest", "normalised", f"channel={ticket.channel}; flags={ticket.quality_flags or 'none'}",
                      input_summary=ticket.text)
            stage = "classification"
            cls = self.classifier.predict(ticket)
            out.update(intent=cls.intent, urgency=cls.urgency, confidence=cls.intent_confidence)
            metrics.CONFIDENCE.observe(cls.intent_confidence or 0)
            self._log(run_id, ticket, "classification", "classified",
                      f"intent {cls.intent} ({cls.intent_confidence:.2f}), urgency {cls.urgency} ({cls.urgency_confidence:.2f})"
                      + (f"; {cls.note}" if cls.note else ""),
                      input_summary=ticket.text, prediction={"intent": cls.intent, "urgency": cls.urgency},
                      confidence=cls.intent_confidence, alternatives=cls.alternatives)
            stage = "retrieval"
            passages = self.retriever.search(ticket.text)
            if self.retriever.backend != "dense":
                out["degraded"].append("retrieval_tfidf_fallback")
            out["sources"] = [{"doc_id": p.doc_id, "passage_id": p.passage_id, "score": p.score} for p in passages]
            self._log(run_id, ticket, "retrieval", "retrieved" if passages else "no_hit",
                      f"{len(passages)} passage(s) above relevance floor {self.retriever.min_score:.2f}",
                      input_summary=ticket.text, sources_used=out["sources"], threshold_applied=self.retriever.min_score)
            stage = "routing"
            ks = kill_switch_on()
            metrics.KILL_SWITCH.set(1 if ks else 0)
            dec = route.decide(cls, passages, kill_switch=ks, intent_docs=self.intent_docs)
            out["route_action"] = dec.action
            self._log(run_id, ticket, "routing", dec.action, dec.reason, input_summary=ticket.text,
                      prediction={"intent": cls.intent}, confidence=cls.intent_confidence, threshold_applied=dec.threshold,
                      sources_used=out["sources"], alternatives=cls.alternatives)
            # ---- input guardrail runs on every ticket, before any model sees the text
            inp = guardrails.check_input(ticket.text)
            if inp.blocked:
                self._count_blocks(inp)
                out["guardrails"] = inp.as_dict()
                out["action"] = "block"
                out["reason"] = "Blocked by guardrail before generation: " + inp.reason()
                pkt_dec = route.RouteDecision("escalate", out["reason"], dec.threshold, "guardrail_input", ("instruction integrity",))
                out["escalation_packet"] = route.build_escalation_packet(ticket, cls, passages, pkt_dec)
                out["escalation_packet"]["original_text"] = ticket.original_body   # record input for review
                self._log(run_id, ticket, "validation", "block", out["reason"], input_summary=ticket.text,
                          guardrail_results=out["guardrails"])
                return self._finish(run_id, ticket, out, t0)
            if dec.action == "escalate":
                out["action"] = "escalate"
                out["reason"] = dec.reason
                out["escalation_packet"] = route.build_escalation_packet(ticket, cls, passages, dec)
                out["response"] = route.ACK_TEXT
                out["guardrails"] = inp.as_dict()
                return self._finish(run_id, ticket, out, t0)
            stage = "generation"
            llm = self.llm if use_llm else LLMClient(enabled=False)
            gen_passages = select_for_generation(passages)
            gen = generate(ticket, gen_passages, llm, self.retriever)
            out["generation_source"] = gen.source
            if gen.source == "template":
                out["degraded"].append("llm_fallback_template")
                metrics.LLM_FALLBACKS.inc()
            self._log(run_id, ticket, "generation", "generated" if gen.can_answer else "no_answer",
                      gen.note or f"{gen.source} answer with {len(gen.sentences)} sentence(s)", input_summary=ticket.text,
                      model={"name": gen.model or self.llm.model, "version": config.SYSTEM_VERSION},
                      sources_used=out["sources"], prompt_version=gen.prompt_version)
            if not gen.can_answer:
                dec2 = route.RouteDecision("escalate", "The documentation retrieved does not answer this question; "
                                           + (gen.note or ""), dec.threshold, "generation_cannot_answer", ("answer content",))
                out.update(action="escalate", reason=dec2.reason, response=route.ACK_TEXT)
                out["escalation_packet"] = route.build_escalation_packet(ticket, cls, passages, dec2)
                return self._finish(run_id, ticket, out, t0)
            stage = "validation"
            text = render(gen.sentences, self.retriever)
            by_id = {p.passage_id: p for p in gen_passages}
            rep = guardrails.check_response(text, gen.sentences, by_id, cls.intent_confidence, dec.threshold, ticket.text)
            out["guardrails"] = rep.as_dict()
            self._log(run_id, ticket, "validation", "block" if rep.blocked else "pass",
                      rep.reason() or "all guardrails passed", input_summary=ticket.text, guardrail_results=out["guardrails"],
                      prompt_version=gen.prompt_version)
            if rep.blocked:
                self._count_blocks(rep)
                out["action"] = "block"
                out["reason"] = "Blocked by guardrail: " + rep.reason()
                pkt_dec = route.RouteDecision("escalate", out["reason"], dec.threshold, "guardrail_output",
                                              tuple(r.name for r in rep.failed))
                out["escalation_packet"] = route.build_escalation_packet(ticket, cls, passages, pkt_dec,
                                                                         draft_note="Draft withheld by guardrail; not sent to customer.")
                out["blocked_draft"] = text
                out["response"] = route.ACK_TEXT
            else:
                out.update(action="auto_respond", reason=dec.reason, response=text)
                out["cited_passages"] = sorted({s for x in gen.sentences for s in x["sources"]})
        except Exception as e:   # defined degradation: escalate, record, continue (A11)
            log.exception("stage %s failed for %s", stage, ticket.ticket_id)
            out.update(action="escalate", error=f"{stage}: {type(e).__name__}",
                       reason=f"System error in {stage} stage ({type(e).__name__}); escalated to a person.",
                       response=route.ACK_TEXT)
            out["degraded"].append(f"error_{stage}")
        return self._finish(run_id, ticket, out, t0)

    # ------------------------------------------------------------------
    def _finish(self, run_id, ticket, out, t0):
        out["latency_s"] = round(time.perf_counter() - t0, 4)
        metrics.LATENCY.observe(out["latency_s"])
        metrics.TICKETS.labels(channel=ticket.channel, outcome=out["action"]).inc()
        try:
            self._log(run_id, ticket, "outcome", out["action"], out["reason"] or "n/a", input_summary=ticket.text,
                      prediction={"intent": out["intent"], "urgency": out["urgency"]}, confidence=out["confidence"],
                      sources_used=out["sources"], guardrail_results=out["guardrails"])
        except Exception:
            log.exception("failed to write outcome row for %s", ticket.ticket_id)
        return out

    def _count_blocks(self, rep):
        for r in rep.failed:
            metrics.GUARDRAIL.labels(guardrail=r.name).inc()

    def _log(self, run_id, ticket, stage, action, reason, **kw):
        kw.setdefault("model", self.model_info)
        kw.setdefault("requirement_ids", REQ.get(stage, []))
        kw.setdefault("prompt_version", "PR-01 v1.0" if stage in ("generation", "validation") else "")
        return self.dlog.log(run_id, ticket.ticket_id, stage, action, reason, **kw)
