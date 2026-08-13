from __future__ import annotations

import json
from typing import Any, Callable

from .bindings import ResourceBindings
from .context import current_agent
from .wechat_bound import BoundWeChatDesktop


def _result(fn: Callable[[], Any]) -> str:
    try:
        return json.dumps({"ok": True, "data": fn()}, ensure_ascii=False, default=str)
    except Exception as exc:
        return json.dumps({"ok": False, "error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False)


def bound_wechat_available() -> bool:
    try:
        ResourceBindings().require(current_agent(), "wechat", ready=True)
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
            "policy": "bound-only",
        }
    return _result(load)


def wechat_status(args: dict, **kwargs) -> str:
    del args, kwargs
    agent = current_agent()
    return _result(lambda: BoundWeChatDesktop(agent).status())


def wechat_list_chats(args: dict, **kwargs) -> str:
    del kwargs
    agent = current_agent()
    return _result(lambda: [row.to_dict() for row in BoundWeChatDesktop(agent).list_chats(int(args.get("limit", 50)))])


def wechat_get_unread_chats(args: dict, **kwargs) -> str:
    del kwargs
    agent = current_agent()
    return _result(lambda: [row.to_dict() for row in BoundWeChatDesktop(agent).unread_chats(int(args.get("limit", 50)))])


def wechat_get_messages(args: dict, **kwargs) -> str:
    del kwargs
    agent = current_agent()
    return _result(lambda: BoundWeChatDesktop(agent).get_messages(str(args.get("chat") or ""), int(args.get("limit", 20))))


def wechat_send_message(args: dict, **kwargs) -> str:
    del kwargs
    agent = current_agent()
    return _result(lambda: BoundWeChatDesktop(agent).send_message(str(args.get("chat") or ""), str(args.get("text") or ""), dry_run=bool(args.get("dry_run", False))))


RESOURCE_LIST = {
    "name": "resource_list",
    "description": "List only the Windows WeChat/browser resources explicitly bound to this Agent. Unbound resources are never exposed.",
    "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
}

BOUND_BROWSER = {
    "name": "bound_browser",
    "description": "Return this Agent's one usable bound browser/CDP endpoint. Fails closed when no ready browser is bound.",
    "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
}
