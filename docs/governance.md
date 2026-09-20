# Governance framework: completed

## 1. Decision logging
Every stage of every ticket writes a row to `storage/decisions.db` (table `decisions`) with: decision_id, run_id, timestamp, ticket_id, stage (ingest, classification, retrieval, routing, generation, validation, outcome), input_summary, model {name, version, classifier, retrieval}, prediction, confidence, alternatives, sources_used {doc_id, passage_id, score}, threshold_applied, action_taken, reason (plain language), guardrail_results, prompt_version, requirement_ids. This is the minimum record from the framework plus `run_id` and the ingest/retrieval/outcome stages.

**Coverage check:** exactly one `outcome` row is written for every ticket, including malformed input and stage failures. On the validation run (80 tickets) the log holds 526 rows with 80 outcome rows for 80 distinct tickets: reconciles exactly. `DecisionLog.reconcile()` performs the check and the harness reports it; `test_decision_log_reconciles` covers a set including a `None` record and an empty record.

## 2. Risk register
Likelihood and impact are H/M/L for this system as built. Owner is the accountable role at CloudServe; the project author owns build-time mitigations until hand-over.

| ID | Risk | L | I | Mitigation in the design (control, not hope) | Owner |
|---|---|---|---|---|---|
| R-01 | Answers confidently and incorrectly | M | H | Model receives only retrieved passages; every sentence must cite a retrieved passage and pass the grounding guardrail (block + escalate); model can answer "cannot answer"; must-escalate policy for security/compliance/feature/unclear intents (0 violations on validation); automation disclosed in every reply. **Residual:** 18 of 63 auto-answers on validation disagreed with the reference route label (see report s7); recommend agent-review ("shadow") mode for the first weeks. | Head of Support |
| R-02 | Private data in an outbound response | L | H | PII guardrail (emails, phones, keys, cards, customer ids, IPs, known customer names) blocks and escalates, never redacts-and-sends; the reply template never uses the customer's name; outbound re-scan in the metrics report (0 occurrences). | Head of Support / DPO |
| R-03 | Customer text treated as an instruction | M | H | Ticket passed as delimited data with `<`/`>` neutralised; instruction-integrity guardrail runs on every ticket before the model sees it and blocks; routing does not depend on the model. Test: `test_injection_ticket_is_blocked`. | Engineering lead |
| R-04 | Some customer groups get worse answers | M | M | Fairness audit in every metrics report (tier, region, fluency, channel, length). **Found:** citation accuracy 50.0% for non-fluent vs 78.72% fluent (n=19 vs 61). Mitigation planned: query rewriting for non-fluent text; until then non-fluent tickets should be sampled for human review. | Head of Support |
| R-05 | Documentation goes stale | M | M | Every answer cites article ids so a wrong answer can be traced to article vs. system (Ines Varga); articles carry `last_reviewed_days_ago`; escalation packet shows the article used. Owner reviews articles cited in escalated-then-corrected tickets. | Technical Writer |
| R-06 | Model provider unavailable | H | M | Timeout, retry with backoff, circuit breaker, extractive template fallback: run with the model fully disabled processed 80 of 80 tickets, 61 answered from templates, log reconciles. | Engineering lead |
| R-07 | Latency degrades under load | M | M | Routing/classification/retrieval are local (about 10 ms). Model calls only for tickets routed to auto. Measured p95 9.5891 s exceeds the 3 s target, driven by the free-tier provider; mitigation: streaming acknowledgement in chat, paid/dedicated endpoint. | Engineering lead |
| R-08 | Cost grows with volume | L | L | Small model, one call per auto-answered ticket, on-disk response cache, answer prompt limited to one article. A full validation run used 59 calls. | Head of Support |
| R-09 | Drift: ticket mix changes and classifier confidence stops meaning what it did | M | M | Confidence histogram exported to Prometheus for drift monitoring; calibration table in every report; retrain from `data/` is one command. | Engineering lead |
| R-10 | Circuit breaker or fallback hides a persistent outage | L | M | `llm_fallbacks_total` metric and `degraded` flag on every affected ticket. | Engineering lead |

## 3. Fairness audit
**Method.** Validation set (80 tickets, labels known). For each segment: auto-answer rate; resolution rate (auto-answered and reference route also auto, divided by tickets whose reference route is auto); citation accuracy (share of auto-answered tickets that cite at least one expected article); intent accuracy; median latency. Gap = best segment minus this segment, only for segments with n at least 5. Segments overlap, so gaps are not additive. Sample sizes are small, so a 5-point threshold is within noise for most rows; treat findings as indicators, not proof.

| Segment | n | Resolution % | Citation accuracy % | Gap in citation accuracy (pts) | Explanation |
|---|---|---|---|---|---|
| Enterprise | 8 | 83.33 | 83.3 | 0.0 | very few tickets; auto-answer rate 75.0% vs 93.33% for business |
| Business | 30 | 100.0 | 75.0 | 8.3 | best resolution |
| Standard | 42 | 90.5 | 65.5 | 17.8 | more loosely worded tickets |
| Fluent English | 61 | 92.5 | 78.72 | 0.0 | reference |
| **Non-fluent English** | 19 | 100.0 | **50.0** | **28.7** | retrieval depends on wording matching the documentation |
| Short tickets (<100 chars) | 10 | 100 | 75.0 | 0.0 | but auto-answer rate only 40.0% vs 84.29%: short tickets are escalated more |
| Long tickets | 70 | 93.3 | 71.2 | 3.8 | |

Full per-segment tables (region, channel) are in `metrics_report.md`. **Findings:** (1) non-fluent tickets are answered just as often but cite the right article far less reliably: the exact fairness problem the framework predicts for retrieval systems. (2) North America has the lowest citation accuracy (61.9% vs 82.35% Asia-Pacific), which I cannot explain from the data and would not over-interpret at n=27. (3) Short tickets are escalated more often, which is fair to customers (a human reads them) but reduces automation for chat users. Historical data shows no fluency or tier gap in resolution (`docs/data_findings.md`), so the gaps above are introduced or revealed by the system rather than inherited.

## 4. Guardrails
| Guardrail | What it checks | When it fires |
|---|---|---|
| instruction_integrity | ticket text tries to override rules, change role, or extract the prompt | block, escalate, original text kept in the packet for review |
| pii | emails, phone numbers, API keys/tokens, card numbers, customer ids, IPs, names of known customers | block and escalate; never redact-and-send |
| grounding | every sentence has a citation resolving to a retrieved passage; content words and numbers supported by the cited article | block and escalate with the unsupported sentence named |
| tone_scope | commitments: refunds, credits, fixes, dates, guarantees | block |
| confidence_floor | routing confidence exists and is at or above the threshold (missing = low, not high) | block |

All five run on every generated response before release, are logged with results whether or not they block, and have **no disable flag**. Unit tests exercise each; the offline run showed the grounding guardrail blocking 2 template answers.

## 5. Incident response
Written for someone unfamiliar with the system at 02:00.

| Step | What to do | Who | How long |
|---|---|---|---|
| 1. Detect | Any of: a customer reports a wrong or leaky automated reply; Grafana shows guardrail blocks or `llm_fallbacks_total` spiking; a decision-log spot check finds a bad answer | On-call support engineer | continuous |
| 2. Contain | **Turn on the kill switch**: `curl -X POST "http://HOST:8000/admin/kill-switch?on=true" -H "X-Admin-Token: $ADMIN_TOKEN"`, or on the server `touch storage/KILL_SWITCH`. All new tickets now escalate to humans. | On-call engineer | under 1 minute |
| 3. Assess | Open `storage/decisions.db`: `SELECT * FROM decisions WHERE ticket_id='<id>' ORDER BY timestamp;` The rows show classification, retrieval, routing reason, sources, guardrail results, prompt version. Decide: wrong article, misread article, guardrail miss, or wrong route. | Engineering lead | 30 min |
| 4. Notify | Head of Support; affected customer gets a human correction; if private data left the system, the data protection officer within the legal window. | Head of Support | 1 h |
| 5. Remediate | Fix the article (Technical Writer), the threshold/intent rule, or the guardrail pattern; add a regression test with the offending ticket; re-run `python -m pytest tests/` and the harness. Turn the switch off: `on=false` or delete `storage/KILL_SWITCH`. | Engineering lead | same day |
| 6. Review | Add to risk register; check whether other tickets in the log had the same signature (query by intent/article). | Head of Support + engineering | within 1 week |

**Kill switch.** Mechanism: file `storage/KILL_SWITCH` checked on every ticket, or the admin endpoint (token-protected). Authorised: on-call engineer and Head of Support. Effect: the next ticket, no deployment. Tickets in flight: finish their current stage; anything not yet routed escalates. Tested by `test_kill_switch_forces_escalation`.

## 6. The declaration
| Statement | Position |
|---|---|
| This system must never | send a customer an answer that is not supported by a retrieved CloudServe article, reveal private data, answer security, compliance, feature-request or unclear tickets automatically, or promise money or dates |
| The mechanism that enforces that is | deterministic routing policy, five blocking guardrails on every response, escalation on any failure, and a kill switch; no model decides whether to answer |
| The most likely way it could still cause harm is | an answer that is grounded in a correct article but does not fit this customer's situation (18 of 63 validation auto-answers disagreed with the reference route), or lower-quality retrieval for non-fluent customers |
| We would not deploy this without first | running it in shadow mode with an agent reviewing every automated reply, human two-assessor review of at least 50 answers, and evaluating on fresh tickets and real customer feedback |
