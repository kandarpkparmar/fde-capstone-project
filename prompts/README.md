# Prompt register

| ID | Name | Category | Version | Serves | File |
|----|------|----------|---------|--------|------|
| PR-01 | Grounded answer generation (JSON, cited) | Build | 1.0 | FR-04, FR-05, FR-06 | build/PR-01_answer_generation.md |
| PR-02 | Escalation summary (template, no model) | Build | 1.0 | FR-07 | build/PR-02_escalation_summary.md |
| PR-03 | Response quality judge (proxy CSAT / hallucination) | Evaluation | 1.0 | NFR-03 | evaluation/PR-03_response_quality_judge.md |

Each file starts with a small header (`prompt_id`, `version`, `serves`) followed by `---` and the prompt text.
The runtime loads them through `src/prompts.py` and logs `"PR-01 v1.0"` in every decision-log row.
Full change history and known weaknesses are in the Stage 3 workbook.
