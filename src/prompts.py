"""Loads versioned prompts from prompts/ (prompts are design artefacts, not inline strings)."""
from functools import lru_cache

from . import config


@lru_cache(maxsize=None)
def load_prompt(relpath: str) -> tuple[str, str]:
    """Return (label like 'PR-01 v1.0', prompt text)."""
    raw = (config.PROMPT_DIR / relpath).read_text()
    head, _, body = raw.partition("\n---\n")
    meta = dict(l.split(": ", 1) for l in head.splitlines() if ": " in l)
    return f"{meta.get('prompt_id', '?')} v{meta.get('version', '?')}", body.strip()
