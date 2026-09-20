"""Prometheus metrics (monitoring, R-07). Exposed at /metrics by the API."""
from prometheus_client import Counter, Histogram, Gauge

TICKETS = Counter("tickets_processed_total", "Tickets processed", ["channel", "outcome"])
LATENCY = Histogram("response_seconds", "End to end ticket handling time",
                    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 3, 5, 10, 30))
GUARDRAIL = Counter("guardrail_blocks_total", "Responses blocked", ["guardrail"])
CONFIDENCE = Histogram("classifier_confidence", "Intent confidence", buckets=[i / 10 for i in range(1, 11)])
LLM_FALLBACKS = Counter("llm_fallbacks_total", "Answers produced by the template because the model was unavailable")
KILL_SWITCH = Gauge("kill_switch_on", "1 when automatic answering is disabled")
