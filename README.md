# CloudServe Support Triage

![CI](https://github.com/kandarpkparmar/fde-capstone-project/actions/workflows/ci.yml/badge.svg)

Repository: https://github.com/kandarpkparmar/fde-capstone-project

Individual capstone (Forward Deployed AI Engineering). Instead of the chatbot the client asked for, this is a
**triage-and-retrieval system**: it answers the tickets whose answers already exist in CloudServe's documentation
(citing the article), escalates everything else *with context attached* (summary, priority, relevant articles,
what it was unsure about), never auto-answers security/compliance/feature/unclear tickets, and logs every decision.

```
ingest -> classify -> retrieve -> route -> generate -> validate(guardrails) -> answer | escalate | block
                         (every stage writes to the SQLite decision log)
```

## 1. Set up (clean machine, tested from a fresh clone)

Requires Python 3.11 or newer (tested locally on 3.11, 3.13 and 3.14) and internet access on first run (downloads the small embedding model, ~90 MB).

```bash
git clone https://github.com/kandarpkparmar/fde-capstone-project.git && cd fde-capstone-project
python3 -m venv .venv
source .venv/bin/activate                              # Windows: .venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env                                   # then put your OpenRouter key in .env
```

`.env` is git-ignored. Only `OPENROUTER_API_KEY` needs a real value. **Without a key (or with `LLM_ENABLED=0`)
the system still runs end to end** using extractive template answers (acceptance criterion A11), so a missing or
dead key never stops a run.

## 2. Run

| What | Command |
|---|---|
| **Full unattended evaluation** (A9/A10) | `python -m evaluation.harness --input data/validation_tickets.json --output evaluation/results/my_run` |
| Same, against any other file with the ticket schema (e.g. the hidden set) | `python -m evaluation.harness --input /path/to/hidden.json --output evaluation/results/hidden_run` |
| **Tests** (A12) | `python -m pytest tests/ -v` |
| Live demo (4 channels, escalation, guardrail block) | `python -m src.demo` |
| API server (docs at `/docs`, Prometheus at `/metrics/`) | `python -m src.api` |
| Provider outage demo | `LLM_ENABLED=0 python -m src.demo` |

The harness writes to `--output`: `metrics_report.md` and `metrics.json` (all required figures, computed by code),
`results.jsonl` (one line per ticket), `decisions.csv` (the decision log for that run) and `review_sample.csv`
(50 answers for the two-assessor hallucination check). Useful flags: `--no-llm`, `--no-cache`, `--judge N`
(LLM quality-judge sample, default 25, use 0 to skip and save tokens), `--workers N`, `--limit N`.
It exits 0 when the run completes, 2 only if the input file cannot be read at all.

Model responses are cached in `storage/llm_cache.sqlite`, so re-runs cost no tokens. The decision log is
`storage/decisions.db` (table `decisions`; one `outcome` row per ticket; `reconcile()` checks the counts).

Example ticket to the API:

```bash
curl -s localhost:8000/ticket -H 'content-type: application/json' -d '{"ticket_id":"T1","channel":"chat","body":"how do I roll back a failed release?"}'
```

## 3. Layout

| Path | Contents |
|---|---|
| `src/ingest.py` | FR-01 normalise 4 channels, never raises |
| `src/classify.py` | FR-02 TF-IDF + logistic regression, calibrated confidence, alternatives, fallback class |
| `src/retrieve.py` | FR-03 Chroma + MiniLM, section chunking, relevance floor, TF-IDF fallback |
| `src/route.py` | FR-05/07 deterministic routing, reasons, escalation packet |
| `src/generate.py` | FR-04 grounded JSON answers with citations; template fallback |
| `src/guardrails.py` | FR-06 five guardrails that block (instruction integrity, PII, grounding, tone/scope, confidence floor) |
| `src/llm.py` | OpenRouter client: timeout, retries, backoff, circuit breaker, cache |
| `src/logging_store.py`, `src/pipeline.py`, `src/api.py`, `src/metrics.py` | FR-08 decision log, orchestration, FastAPI + kill switch, Prometheus |
| `prompts/` | versioned prompt library and register |
| `evaluation/` | harness, metrics, judge, threshold tuning, chunking experiment, discovery analysis, `results/` |
| `tests/` | 22 tests covering A2-A8, A11 and the harness |
| `docs/` | architecture, decisions, traceability, data findings, governance |
| `monitoring/`, `.github/workflows/ci.yml` | Prometheus/Grafana config, CI |

Kill switch: `POST /admin/kill-switch?on=true` with header `X-Admin-Token` (needs `ADMIN_TOKEN` in `.env`), or simply
create the file `storage/KILL_SWITCH`. Takes effect on the next ticket, no deployment; all tickets then escalate.

## 4. Attribution and AI-tool declaration

Most of this code and documentation was written with **Claude Code (Claude Sonnet 5)** under the author's direction.
Third-party libraries: scikit-learn, sentence-transformers (`all-MiniLM-L6-v2`), ChromaDB, FastAPI, prometheus-client,
requests, pytest. Design decisions and their rationale are in `docs/decisions.md`. See the report's AI-use declaration.

## 5. Known limits (also in the report)

* p95 latency is dominated by the free-tier model provider and exceeds the 3 s target.
* About 20% of documentation-covered tickets carry `answerable=False` labels that identical-looking tickets do not share,
  so routing accuracy against labels is capped; see `docs/data_findings.md`.
* Scores on the development/validation data are optimistic because ticket wording is templated (216 unique texts in 500).
