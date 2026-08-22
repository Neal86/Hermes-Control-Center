from __future__ import annotations

import hashlib
import re
from typing import Any

_MENTION_MARKERS = (
    "有人@我",
    "[有人@我]",
    "【有人@我】",
    "@我",
    "提到了你",
    "mentioned you",
    "mentioned me",
)


def normalize_preview(preview: str) -> str:
    text = str(preview or "").strip()
    if not text:
        return ""
    return re.sub(r"^\s*(?:(?:上午|下午)\s*)?\d{1,2}:\d{2}\s*", "", text).strip()


def group_mentions_me(text: str) -> bool:
    value = str(text or "").lower()
    return any(marker in value for marker in _MENTION_MARKERS)


def trailing_inbound(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return consecutive inbound/unknown rows after the most recent outbound.

    Modern WeChat UIA bubbles do not always expose trustworthy left/right
    geometry. Unknown direction must therefore remain a receive candidate rather
    than being silently discarded.
    """
    tail: list[dict[str, Any]] = []
    for row in reversed(messages):
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        direction = str(row.get("direction") or "").strip().lower()
        if direction == "outbound":
            break
        if direction in {"", "inbound", "unknown"}:
            tail.append(row)
    tail.reverse()
    return tail


def message_fingerprint(chat: str, rows: list[dict[str, Any]]) -> str:
    parts = [chat]
    for row in rows:
        parts.extend(
            [
                str(row.get("message_id") or ""),
                str(row.get("sender") or ""),
                str(row.get("time") or ""),
                str(row.get("text") or ""),
                str(row.get("direction") or ""),
            ]
        )
    return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()


def compact_context(messages: list[dict[str, Any]], limit: int = 12) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in messages[-max(1, int(limit)):]:
        result.append(
            {
                "text": str(row.get("text") or "").strip(),
                "sender": str(row.get("sender") or "").strip() or None,
                "direction": str(row.get("direction") or "").strip().lower() or None,
                "time": row.get("time"),
                "message_id": row.get("message_id"),
            }
        )
    return result


def infer_chat_type(chat: str, messages: list[dict[str, Any]], *, known_group: bool, mentioned: bool) -> str:
    if known_group or mentioned:
        return "group"
    if any(
        str(row.get("sender") or "").strip()
        and str(row.get("sender") or "").strip() != chat
        for row in messages
    ):
        return "group"
    return "dm"
