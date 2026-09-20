# Architecture

Six components in sequence over three cross-cutting concerns (decision log, guardrails, monitoring).
Layers: **interface** (FastAPI, harness) -> **orchestration** (`pipeline.py`) -> **components** -> **persistence** (SQLite log, Chroma, cache).

| Component | Choice | Alternatives considered | Why |
|---|---|---|---|
| Classify | TF-IDF (word+char) + logistic regression, temperature-scaled | LLM zero-shot; fine-tuned transformer | Deterministic (A5), free, instant, and its probabilities can be calibration-checked, which the threshold depends on. An LLM classifier costs tokens per ticket and is non-deterministic. |
| Retrieve | MiniLM embeddings in Chroma, one chunk per markdown section, relevance floor | keyword/BM25; whole-article; fixed windows | Ines Varga: keyword search fails because customers do not use the title words. Section chunks keep the Resolution steps whole and measured best MRR (docs/chunking_experiment.json). |
| Route | Pure rule function over classifier + retrieval outputs | LLM decides | Auditable, deterministic, explainable to a compliance review (Marcus). The model never decides whether to answer. |
| Generate | Llama-3.1-8B via OpenRouter, JSON with per-sentence citations, ticket passed as delimited data | larger model; free-text | Small model is enough when the passages are given; JSON makes citations checkable. |
| Validate | Five blocking guardrails on every response | warn-only checks | A guardrail that only warns is not a guardrail. There is no disable flag. |
| Orchestration | Plain Python functions | LangGraph | The flow is linear with one branch; a graph framework would add a dependency without adding clarity. Stated departure from the brief's suggestion. |

## Failure handling (A11)
| Condition | Behaviour |
|---|---|
| No retrieval hit | escalate with reason |
| Provider timeout / 429 / 5xx / down / no key | retry with backoff, circuit breaker, then extractive template answer built from the top passage (still cited and guardrailed) |
| Embedding model or Chroma unavailable | in-memory TF-IDF retrieval (flagged `retrieval_tfidf_fallback`) |
| Unparseable model output | template answer |
| Malformed / empty / huge / odd-encoding ticket | normalised with quality flags; empty text -> fallback class -> escalate |
| Any stage exception | escalate, reason recorded, one `outcome` row still written |

## Escalation packet
priority (P1-P3 from urgency x tier), summary, classifier confidence + alternatives, what the system was unsure about,
top-3 sources with snippets, reason in plain language, original text. The customer receives an acknowledgement that says it
is automated (Ravi Menon: disclosure).
