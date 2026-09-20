# Metrics report - run 20260920T073629-2f3d

Input: `data/validation_tickets.json` | model: meta-llama/llama-3.1-8b-instruct | retrieval: dense/section | wall clock: 227.3 s | cache used: True

## Volume

| Measure | Value |
|---|---|
| tickets processed | 80 |
| answered automatically | 63 |
| escalated | 17 |
| blocked by guardrails | 0 |
| degraded llm fallback | 0 |
| degraded retrieval fallback | 0 |
| stage errors | 0 |

## Business

| Measure | Value |
|---|---|
| First contact resolution (proxy) | 78.75% |
| First contact resolution (verified against labels) | 56.25% |
| Escalation rate | 21.25% |
| Reply time, all tickets (mean / median / p95, s) | 2.8401 / 1.6408 / 9.5891 |
| Historical baseline (FCR / escalation / median resolution min / CSAT) | 46.25% / 53.75% / 218.0 / 2.6 |
| Satisfaction proxy (LLM judge, n=10) | 4.5 / 5 |

_First reply = answer or acknowledgement produced by the system. Time a human then takes on escalated tickets is NOT simulated._

## Technical

Intent accuracy 1.000; weighted precision 1.000; macro recall 1.000 (n=80).

| Intent | Precision | Recall | F1 | Support |
|---|---|---|---|---|
| account_access | 1.0 | 1.0 | 1.0 | 4 |
| api_key_issue | 1.0 | 1.0 | 1.0 | 6 |
| api_usage_question | 1.0 | 1.0 | 1.0 | 4 |
| authentication_failure | 1.0 | 1.0 | 1.0 | 3 |
| billing_query | 1.0 | 1.0 | 1.0 | 10 |
| compliance_request | 1.0 | 1.0 | 1.0 | 1 |
| configuration_help | 1.0 | 1.0 | 1.0 | 3 |
| data_export | 1.0 | 1.0 | 1.0 | 1 |
| data_residency | 1.0 | 1.0 | 1.0 | 6 |
| database_issue | 1.0 | 1.0 | 1.0 | 1 |
| deployment_failure | 1.0 | 1.0 | 1.0 | 5 |
| feature_request | 1.0 | 1.0 | 1.0 | 3 |
| integration_help | 1.0 | 1.0 | 1.0 | 3 |
| onboarding | 1.0 | 1.0 | 1.0 | 4 |
| performance_degradation | 1.0 | 1.0 | 1.0 | 3 |
| quota_or_overage | 1.0 | 1.0 | 1.0 | 2 |
| rate_limit | 1.0 | 1.0 | 1.0 | 1 |
| rollback_request | 1.0 | 1.0 | 1.0 | 6 |
| security_incident | 1.0 | 1.0 | 1.0 | 4 |
| sso_configuration | 1.0 | 1.0 | 1.0 | 1 |
| unclear_request | 1.0 | 1.0 | 1.0 | 6 |
| webhook_issue | 1.0 | 1.0 | 1.0 | 3 |

Urgency accuracy: 0.4375. Calibration ECE: 0.07 points.

| Confidence band | n | Stated | Observed | Gap (pts) |
|---|---|---|---|---|
| 0.8-1.0 | 80 | 0.9993 | 1.0 | -0.07 |

Retrieval hit rate: 96.23% (n=53). Routing: {'accuracy_pct': 73.75, 'auto_answer_precision_pct': 71.43, 'wrongly_auto_answered': 18, 'missed_automation_pct': 6.25, 'note': "Final action vs expected_route label. Includes the labels' irreducible noise (identical tickets carry both labels)."}

Citations: {'citations_checked': 147, 'resolve_to_retrieved_passages_pct': 100.0, 'cite_an_expected_document_pct': 70.07, 'answers_with_expected_doc_cited_pct': 71.43}

Reference-answer checks: {'answers_with_reference': 0, 'must_mention_coverage_pct': None, 'must_not_claim_violations': 0}

Latency (s): {'mean': 2.8401, 'median': 1.6408, 'p95': 9.5891}

Hallucination: {'drafts_blocked_for_unsupported_claims': 0, 'sent_answers_passing_grounding_check_pct': 100.0, 'judge_unsupported_claim_rate_pct': 0.0, 'judge_sample_size': 10, 'note': 'Rate among SENT answers estimated by an LLM judge on a sample; a human review sheet (review_sample.csv) is produced for the required two-assessor check, which this run does not include.'}

## Governance

- Decisions logged: 526 | reconciliation: {'run_id': '20260920T073629-2f3d', 'tickets_processed': 80, 'decisions_logged': 526, 'outcome_rows': 80, 'distinct_tickets_with_outcome': 80, 'by_stage': {'classification': 80, 'generation': 63, 'ingest': 80, 'outcome': 80, 'retrieval': 80, 'routing': 80, 'validation': 63}, 'reconciles': True}
- Guardrail activations: {}
- Private-data detections (blocked): 0
- Private data in outbound responses: 0
- must_not_auto_respond violations: 0

## Fairness segments

**customer_tier**

| Segment | n | Auto-answer % | Resolution % | Citation % | Intent acc % | Gap (resolution) |
|---|---|---|---|---|---|---|
| business | 30 | 93.33 | 100.0 | 75.0 | 100.0 | 0.0 |
| enterprise | 8 | 75.0 | 83.33 | 83.33 | 100.0 | 16.67 |
| standard | 42 | 69.05 | 90.48 | 65.52 | 100.0 | 9.52 |

**customer_region**

| Segment | n | Auto-answer % | Resolution % | Citation % | Intent acc % | Gap (resolution) |
|---|---|---|---|---|---|---|
| asia_pacific | 21 | 80.95 | 86.67 | 82.35 | 100.0 | 13.33 |
| europe | 25 | 84.0 | 100.0 | 71.43 | 100.0 | 0.0 |
| latin_america | 7 | 57.14 | 100.0 | 75.0 | 100.0 | 0.0 |
| north_america | 27 | 77.78 | 92.86 | 61.9 | 100.0 | 7.14 |

**language_fluency**

| Segment | n | Auto-answer % | Resolution % | Citation % | Intent acc % | Gap (resolution) |
|---|---|---|---|---|---|---|
| fluent | 61 | 77.05 | 92.5 | 78.72 | 100.0 | 7.5 |
| non_fluent | 19 | 84.21 | 100.0 | 50.0 | 100.0 | 0.0 |

**channel**

| Segment | n | Auto-answer % | Resolution % | Citation % | Intent acc % | Gap (resolution) |
|---|---|---|---|---|---|---|
| chat | 22 | 72.73 | 92.31 | 68.75 | 100.0 | 7.69 |
| docs_comment | 16 | 68.75 | 87.5 | 63.64 | 100.0 | 12.5 |
| email | 31 | 87.1 | 95.24 | 74.07 | 100.0 | 4.76 |
| forum | 11 | 81.82 | 100.0 | 77.78 | 100.0 | 0.0 |

**ticket_length**

| Segment | n | Auto-answer % | Resolution % | Citation % | Intent acc % | Gap (resolution) |
|---|---|---|---|---|---|---|
| long (>=100 chars) | 70 | 84.29 | 93.33 | 71.19 | 100.0 | 6.67 |
| short (<100 chars) | 10 | 40.0 | 100.0 | 75.0 | 100.0 | 0.0 |

## Targets

| Measure | Baseline | Target | Achieved |
|---|---|---|---|
| First contact resolution | 42% | >= 60% | 78.75% |
| Escalation rate | 58% | <= 30% | 21.25% |
| Mean time to first reply | 8-12 h | < 5 min | 2.8401 s |
| Median time to first reply | n/a | n/a | 1.6408 s |
| Intent classification precision (weighted) | - | >= 85% | 100.0% |
| Citation accuracy (resolves to retrieved passage) | - | >= 95% | 100.0% |
| Latency p95 | - | < 3 s | 9.5891 s |
| Private data in outbound responses | - | 0 | 0 |
| Decision log reconciles | - | exact | True |