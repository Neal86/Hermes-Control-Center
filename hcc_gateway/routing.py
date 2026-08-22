from __future__ import annotations

from typing import Any


def source_chat_id(event_or_metadata: Any) -> str:
    """Resolve an explicit reply route; never fall back to current/last chat."""
    if isinstance(event_or_metadata, dict):
        raw = event_or_metadata
    else:
        raw = getattr(event_or_metadata, "raw_message", {}) or {}
    chat = str(raw.get("source_chat_id") or raw.get("chat") or "").strip()
    if not chat:
        raise ValueError("source_chat_id is required for WeChat reply routing")
    return chat


def build_reply_metadata(chat_id: str) -> dict[str, str]:
    chat = str(chat_id or "").strip()
    if not chat:
        raise ValueError("chat_id is required")
    return {"source_chat_id": chat, "reply_route": "source_chat_only"}
