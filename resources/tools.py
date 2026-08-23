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
    """Resolve WeChat Web through the Agent-bound browser when a WeChat Web tab exists.

    The same Agent-bound browser is a general-purpose browser resource and may also
    be used by Hermes native browser tools for business systems such as Lingxing.
    Desktop WeChat remains a separate Gateway/platform path.
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
            "purpose": "general_web_and_wechat_web",
            "wechat_adapter": "wechat_web_adapter",
            "wechat_driver": "cdp_dom",
            "other_websites": "allowed_on_bound_browser",
            "generic_cdp_browsing_allowed": True,
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
    "description": "Return the Agent-bound general-purpose browser and its CDP endpoint. It may be used for Lingxing, carriers, email, and other websites. If a WeChat Web tab is open, the WeChat Web Adapter may use the same bound browser; Desktop WeChat messaging remains a separate Gateway path.",
    "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
}
