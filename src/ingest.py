"""FR-01 Ingest: normalise tickets from four channels into one internal representation (A2).

Never raises on bad input: missing fields, odd characters and empty bodies are handled
and flagged in `quality_flags` rather than failing.
"""
from __future__ import annotations

import html
import re
import unicodedata
import uuid
from typing import Any, Optional

from pydantic import BaseModel, Field

CHANNELS = ("email", "chat", "docs_comment", "forum")
_ALIASES = {
    "live_chat": "chat", "livechat": "chat", "chat": "chat",
    "email": "email", "mail": "email", "e-mail": "email",
    "docs_comment": "docs_comment", "docs": "docs_comment", "documentation": "docs_comment",
    "doc_comment": "docs_comment", "docs-comment": "docs_comment",
    "forum": "forum", "community": "forum", "community_forum": "forum",
}
MAX_BODY_CHARS = 4000
_TAGS = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class Ticket(BaseModel):
    ticket_id: str
    channel: str = "unknown"
    subject: str = ""
    body: str = ""
    text: str = ""                    # subject + body, cleaned: what downstream components read
    original_subject: str = ""        # preserved verbatim (spec: preserve original text)
    original_body: str = ""
    received_at: Optional[str] = None
    customer_id: str = "unknown"
    customer_name: str = "unknown"
    customer_tier: str = "unknown"
    customer_region: str = "unknown"
    language_fluency: str = "unknown"
    quality_flags: list[str] = Field(default_factory=list)


def _s(v: Any) -> str:
    if v is None:
        return ""
    return v if isinstance(v, str) else str(v)


def clean_text(s: str) -> str:
    s = unicodedata.normalize("NFKC", html.unescape(s))
    s = _TAGS.sub(" ", s)
    s = _CTRL.sub(" ", s)
    return _WS.sub(" ", s).strip()


def normalise(raw: Any) -> Ticket:
    flags: list[str] = []
    if not isinstance(raw, dict):
        flags.append("malformed_record")
        raw = {"body": _s(raw)}
    tid = _s(raw.get("ticket_id")).strip()
    if not tid:
        tid = f"GEN-{uuid.uuid4().hex[:8]}"
        flags.append("missing_ticket_id")
    ch = _ALIASES.get(_s(raw.get("channel")).strip().lower().replace(" ", "_"))
    if ch is None:
        ch = "unknown"
        flags.append("unknown_channel")
    o_sub, o_body = _s(raw.get("subject")), _s(raw.get("body"))
    sub, body = clean_text(o_sub), clean_text(o_body)
    if len(body) > MAX_BODY_CHARS:
        body = body[:MAX_BODY_CHARS]
        flags.append("truncated")
    if not body and not sub:
        flags.append("empty_body")
    text = (sub + ". " + body).strip(". ").strip() if sub else body
    return Ticket(
        ticket_id=tid, channel=ch, subject=sub, body=body, text=text,
        original_subject=o_sub, original_body=o_body,
        received_at=_s(raw.get("received_at")) or None,
        customer_id=_s(raw.get("customer_id")) or "unknown",
        customer_name=_s(raw.get("customer_name")) or "unknown",
        customer_tier=_s(raw.get("customer_tier")) or "unknown",
        customer_region=_s(raw.get("customer_region")) or "unknown",
        language_fluency=_s(raw.get("language_fluency")) or "unknown",
        quality_flags=flags,
    )
