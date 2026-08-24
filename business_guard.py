"""Per-turn guardrails for real-time warehouse/customer-service lookups.

The guard does not prescribe a brittle click path. It injects evidence-based
completion criteria before each LLM call so Hermes keeps autonomous tool
selection while refusing to treat a generic screenshot/tool success or an old
answer as fresh business evidence.
"""
from __future__ import annotations

import json
import re
from typing import Any, Iterable

_BUSINESS_TERMS = (
    "\u8ba2\u5355",  # order
    "\u5e93\u5b58",  # inventory
    "\u7269\u6d41",  # logistics
    "\u5feb\u9012",  # parcel
    "\u8d39\u7528",  # fee
    "\u5165\u5e93",  # inbound
    "\u51fa\u5e93",  # outbound
    "\u9000\u4ef6",  # return
    "\u6362\u6807",  # relabel
    "fba", "sku", "tracking", "shipment", "warehouse", "order",
)
_IDENTIFIER_RE = re.compile(r"\b(?:OBS[A-Z0-9-]{5,}|[A-Z]{2,}[A-Z0-9-]{6,}|\d{8,})\b", re.I)
_QUERY_TOOLS = {
    "browser_type", "browser_console", "browser_navigate", "browser_click", "browser_cdp",
    "computer_use", "terminal", "terminal_exec", "shell", "shell_run",
}
_READ_TOOLS = {
    "browser_snapshot", "browser_console", "browser_cdp", "computer_use", "browser_vision",
}


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except Exception:
        return str(value)


def _is_business_lookup(message: str) -> bool:
    low = message.lower()
    return bool(_IDENTIFIER_RE.search(message)) or any(term in low for term in _BUSINESS_TERMS)


def _identifiers(message: str) -> list[str]:
    seen: list[str] = []
    for match in _IDENTIFIER_RE.findall(message):
        token = match.upper()
        if token not in seen:
            seen.append(token)
    return seen


def _current_turn(history: Iterable[dict[str, Any]], user_message: str) -> list[dict[str, Any]]:
    rows = [row for row in history if isinstance(row, dict)]
    anchor = -1
    fallback = -1
    for i in range(len(rows) - 1, -1, -1):
        if str(rows[i].get("role") or "") != "user":
            continue
        if fallback < 0:
            fallback = i
        if _text(rows[i].get("content")).strip() == str(user_message or "").strip():
            anchor = i
            break
    if anchor < 0:
        anchor = fallback
    return rows[anchor:] if anchor >= 0 else []


def _tool_calls(row: dict[str, Any]) -> list[tuple[str, str]]:
    raw = row.get("tool_calls")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            raw = []
    out: list[tuple[str, str]] = []
    if isinstance(raw, list):
        for call in raw:
            if not isinstance(call, dict):
                continue
            fn = call.get("function") if isinstance(call.get("function"), dict) else {}
            name = str(fn.get("name") or call.get("name") or "")
            args = _text(fn.get("arguments") if "arguments" in fn else call.get("arguments"))
            out.append((name, args))
    return out


def _evidence_state(history: Iterable[dict[str, Any]], user_message: str) -> dict[str, Any]:
    turn = _current_turn(history, user_message)
    ids = _identifiers(user_message)
    query_submitted = False
    query_tool = ""
    result_read_after_query = False
    wrong_page_seen = False
    wrong_page_after_query = False
    tool_activity = False

    for row in turn:
        role = str(row.get("role") or "")
        if role == "assistant":
            for name, args in _tool_calls(row):
                tool_activity = True
                low_name = name.lower()
                compact_args = args.lower().replace(" ", "")
                if "google.com" in compact_args or ('"app":"chrome"' in compact_args and "capture" in compact_args):
                    wrong_page_seen = True
                    if query_submitted:
                        wrong_page_after_query = True
                if low_name in _QUERY_TOOLS and ids and any(token.lower() in compact_args for token in ids):
                    query_submitted = True
                    query_tool = name
                    wrong_page_after_query = False
                elif low_name in _QUERY_TOOLS and not ids and any(term in compact_args for term in _BUSINESS_TERMS):
                    query_submitted = True
                    query_tool = name
                    wrong_page_after_query = False
        elif role == "tool":
            tool_activity = True
            name = str(row.get("tool_name") or "").lower()
            content = _text(row.get("content")).lower()
            if "google.com" in content or ("google" in content and "gmail" in content):
                wrong_page_seen = True
                if query_submitted:
                    wrong_page_after_query = True
            if query_submitted and name in _READ_TOOLS:
                result_read_after_query = True
            if query_submitted and ids and any(token.lower() in content for token in ids):
                result_read_after_query = True

    return {
        "identifiers": ids,
        "tool_activity": tool_activity,
        "query_submitted": query_submitted,
        "query_tool": query_tool,
        "result_read_after_query": result_read_after_query,
        "wrong_page_seen": wrong_page_seen,
        "wrong_page_after_query": wrong_page_after_query,
        "verified_minimum": bool(query_submitted and result_read_after_query and not wrong_page_after_query),
    }


def pre_llm_call(**kwargs: Any) -> dict[str, str] | None:
    """Inject per-turn completion criteria for real-time WeChat business work."""
    platform = str(kwargs.get("platform") or "").lower()
    if "wechat" not in platform:
        return None
    user_message = str(kwargs.get("user_message") or "")
    if not _is_business_lookup(user_message):
        return None

    state = _evidence_state(kwargs.get("conversation_history") or [], user_message)
    ids = ", ".join(state["identifiers"]) or "the requested business object"
    if state["verified_minimum"]:
        return {
            "context": (
                "[NiceC live-business guard] Fresh current-turn query evidence exists. "
                "Before answering, still verify that the result belongs to the requested identifier "
                f"({ids}) and comes from the intended business system. Historical answers are context only."
            )
        }

    seen_note = (
        " A generic Chrome/Google page or capture was seen; that is explicitly NOT business evidence."
        if state["wrong_page_seen"] else ""
    )
    activity_note = (
        " Some tool activity occurred, but the requested identifier has not yet been both submitted and read back from a business result."
        if state["tool_activity"] else " No current-turn business query has been executed yet."
    )
    return {
        "context": (
            "[NiceC live-business guard - MUST CONTINUE, do not finalize yet] "
            f"This is a real-time business lookup for {ids}."
            + activity_note + seen_note +
            " Tool success, a screenshot, or absence of text on an unrelated page is not task success. "
            "Continue autonomously with tools until you enter/find the appropriate business system, "
            "actually submit the requested identifier, read the resulting business record/no-result state, and verify it. "
            "Prefer the Agent-bound browser/CDP for website work instead of capturing an arbitrary personal Chrome window. "
            "Do not reuse a prior turn's 'not found' answer as fresh evidence. Do not tell the customer 'not found', status, inventory, "
            "tracking, fee, or any other real-time fact without fresh verified evidence. "
            "If a method fails, try a materially different reasonable method. If genuinely blocked after reasonable alternatives, "
            "escalate internally to owner Neal rather than inventing a customer-facing result."
        )
    }


__all__ = ["pre_llm_call", "_evidence_state", "_is_business_lookup"]
