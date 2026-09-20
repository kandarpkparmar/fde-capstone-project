"""Central configuration. Everything is read from the environment (.env) with safe defaults.

Requirement traceability: NFR-07 (cost), NFR-05 (auditability) - see docs/requirements_traceability.md
"""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _path(name: str, default: str) -> Path:
    p = Path(os.getenv(name, default))
    return p if p.is_absolute() else (ROOT / p).resolve()


DATA_DIR = _path("DATA_DIR", "data")
STORAGE_DIR = _path("STORAGE_DIR", "storage")
CHROMA_PATH = _path("CHROMA_PATH", "storage/chroma")
DB_PATH = _path("DB_PATH", "storage/decisions.db")
LLM_CACHE_PATH = _path("LLM_CACHE_PATH", "storage/llm_cache.sqlite")
MODEL_CACHE_PATH = _path("MODEL_CACHE_PATH", "storage/classifier.joblib")
KILL_SWITCH_FILE = _path("KILL_SWITCH_FILE", "storage/KILL_SWITCH")
PROMPT_DIR = ROOT / "prompts"

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
MODEL_NAME = os.getenv("MODEL_NAME", "meta-llama/llama-3.1-8b-instruct")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
LLM_TIMEOUT_S = float(os.getenv("LLM_TIMEOUT_S", "25"))
LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "2"))
LLM_ENABLED = os.getenv("LLM_ENABLED", "1") not in ("0", "false", "False")

RETRIEVAL_TOP_K = int(os.getenv("RETRIEVAL_TOP_K", "4"))
# Set from data by evaluation/tune_thresholds.py (see docs/threshold_decision.md).
CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", "0.80"))
ANSWERABLE_THRESHOLD = float(os.getenv("ANSWERABLE_THRESHOLD", "0.50"))
RETRIEVAL_MIN_SCORE = float(os.getenv("RETRIEVAL_MIN_SCORE", "0.30"))
CHUNK_STRATEGY = os.getenv("CHUNK_STRATEGY", "section")

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
SYSTEM_VERSION = "1.0.0"

# Intents that must never be answered automatically (Dataset guide: must_not_auto_respond;
# Daniel Okonkwo interview: security, billing disputes, data location; Ines Varga: feature requests).
MUST_ESCALATE_INTENTS = frozenset(
    {"security_incident", "compliance_request", "feature_request", "unclear_request"}
)
