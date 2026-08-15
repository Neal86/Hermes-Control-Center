from __future__ import annotations

import json
from typing import Any, Callable

from .bindings import ResourceBindings
from .context import current_agent
from .wechat_web import WeChatWebAdapter


def _result(fn: Callable[[], Any]) -> str:
    try:
        return json.dumps({"ok": True, "data": fn()}, ensure_ascii=False, default=str)
    except Exception as exc:
        return json.dumps({"ok": False, "error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False)


def _wechat_backend(agent: str) -> WeChatWebAdapter:
    """Resolve WeChat only through WeChat Web Adapter -> CDP -> DOM.

    Desktop WeChat is deliberately not used as a fallback. This keeps routing
    deterministic: WeChat => dedicated Web Adapter over CDP; all other web work
    => Hermes native browser/computer-use tools.
    """
    ResourceBindings().require(agent, "browser", ready=True)
    adapter = WeChatWebAdapter(agent)
    status = adapter.status()
    if not status.get("url"):
        raise RuntimeError("bound browser has no open WeChat Web tab")
    return adapter


def bound_wechat_available() -> bool:
    try:
        _wechat_backend(current_agent())
        return True
    except Exception:
        return False


def resource_list(args: dict, **kwargs) -> str:
    del args, kwargs
    agent = current_agent()
    return _result(lambda: {"agent": agent, "items": ResourceBindings().resources_for_agent(agent, refresh=True), "policy": "bound-only"})


def bound_browser(args: dict, **kwargs) -> str:
    del args, kwargs
    agent = current_agent()

    def load():
        row = ResourceBindings().require(agent, "browser", ready=True)
        port = row.get("debug_port")
        if not port:
            raise RuntimeError("bound browser has no usable CDP port")
        return {
            "agent": agent,
            "resource": row,
            "cdp_url": f"http://127.0.0.1:{int(port)}",
            "purpose": "wechat_web_only",
            "wechat_adapter": "wechat_web_adapter",
            "wechat_driver": "cdp_dom",
            "other_websites": "hermes_native_browser",
            "generic_cdp_browsing_allowed": False,
            "policy": "bound-only",
        }

    return _result(load)


def wechat_status(args: dict, **kwargs) -> str:
    del args, kwargs
    agent = current_agent()
    return _result(lambda: _wechat_backend(agent).status())


def wechat_list_chats(args: dict, **kwargs) -> str:
    del kwargs
    agent = current_agent()

    def load():
        rows = _wechat_backend(agent).list_chats(int(args.get("limit", 50)))
        return [row.to_dict() if hasattr(row, "to_dict") else row for row in rows]

    return _result(load)


def wechat_get_unread_chats(args: dict, **kwargs) -> str:
    del kwargs
    agent = current_agent()

    def load():
        rows = _wechat_backend(agent).unread_chats(int(args.get("limit", 50)))
        return [row.to_dict() if hasattr(row, "to_dict") else row for row in rows]

    return _result(load)


def wechat_get_messages(args: dict, **kwargs) -> str:
    del kwargs
    agent = current_agent()
    return _result(lambda: _wechat_backend(agent).get_messages(str(args.get("chat") or ""), int(args.get("limit", 20))))


def wechat_send_message(args: dict, **kwargs) -> str:
    del kwargs
    agent = current_agent()
    return _result(
        lambda: _wechat_backend(agent).send_message(
            str(args.get("chat") or ""),
            str(args.get("text") or ""),
            dry_run=bool(args.get("dry_run", False)),
        )
    )


RESOURCE_LIST = {
    "name": "resource_list",
    "description": "List only the Windows WeChat/browser resources explicitly bound to this Agent. Unbound resources are never exposed.",
    "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
}

BOUND_BROWSER = {
    "name": "bound_browser",
    "description": "Return the Agent-bound browser reserved for the WeChat Web Adapter. The adapter uses CDP internally; do not use this CDP browser for Lingxing, carriers, email, or other websites. Use Hermes native browser/computer-use capabilities for those.",
    "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
}
