# Traceability: discovery evidence -> requirement -> prompt -> code -> test -> decision log

| Req | Evidence (Stage 1 ref) | Prompt | Code | Test | Logged as |
|---|---|---|---|---|---|
| FR-01 Ingest 4 channels | Brief s1 (channels); 5 transcripts | - | src/ingest.py | test_components::test_four_channels..., test_ingest_handles_bad_input | stage `ingest` |
| FR-02 Classify intent+urgency, calibrated confidence | S2 data table (22 intents); Marcus "guessing" | - | src/classify.py | test_classification_..., test_classifier_fallback_on_empty | stage `classification` |
| FR-03 Retrieve with relevance floor | Ines (keyword search), Sofia (findability), S2 answerable 71% | - | src/retrieve.py | test_retrieval_* | stage `retrieval` |
| FR-04 Grounded cited answers, "I don't know" | Marcus (wrong answer = failure), Ravi | PR-01 | src/generate.py | test_end_to_end_answer_has_resolvable_citations | stage `generation` |
| FR-05 Deterministic routing, threshold from data, never auto for must-escalate | Marcus, Daniel, Ines; S2 must_not 17% | - | src/route.py | test_routing_is_deterministic..., test_never_auto_answers... | stage `routing` |
| FR-06 Guardrails that block | Marcus (screenshot risk), Governance framework | - | src/guardrails.py | test_guardrails_block, test_injection_ticket_is_blocked, test_model_leaking..., test_commitment_is_blocked | stage `validation` |
| FR-07 Escalation packet | Daniel ("show its working"), Sofia ("draft and page attached") | PR-02 | src/route.py::build_escalation_packet | test_no_retrieval_hit_escalates | stage `routing` |
| FR-08 Decision log, reconciles | Marcus (compliance review) | - | src/logging_store.py, src/pipeline.py | test_decision_log_reconciles | all stages, `outcome` |
| FR-09 Disclose automation | Ravi | PR-01 / footer | src/generate.py::FOOTER | (rendered text) | - |
| FR-10 Priority for escalations by urgency and tier | Ravi (4pm vs 9am), S2 tier table | - | route.build_escalation_packet | - | packet |
| FR-11 One-command harness, metrics report | Build spec A9/A10 | - | evaluation/harness.py | test_harness_end_to_end | - |
| FR-12 Kill switch | Governance framework | - | src/pipeline.py, src/api.py | test_kill_switch_forces_escalation | routing reason |
| FR-13 Fairness segmentation | Sofia (non-fluent), Ravi (tiers) | - | evaluation/report_metrics.py | harness test | metrics.json |
| FR-14 Graceful degradation | Build spec A11 | - | src/llm.py, src/generate.py | test_provider_outage_degrades_and_continues, test_malformed_input_... | `degraded` flags |
