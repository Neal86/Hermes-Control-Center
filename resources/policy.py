from __future__ import annotations

import os
from typing import Any

from .bindings import ResourceAccessError, ResourceBindings
from .context import current_agent

_BROWSER_PREFIXES = ("browser_",)
_BROWSER_NAMES = {"browser", "browser_exec", "browser_cdp"}


def _is_browser_tool(name: str) -> bool:
    value = str(name or "").strip()
    return value in _BROWSER_NAMES or any(value.startswith(prefix) for prefix in _BROWSER_PREFIXES)


def pre_tool_call(tool_name: str, args: dict[str, Any], task_id: str = "", **kwargs):
    del args, task_id, kwargs
    if not _is_browser_tool(tool_name):
        return None

    # WeChat binding does not restrict generic Hermes capabilities. A WeChat-bound
    # Agent may still use computer_use, clarify, and other non-browser tools. Only
    # browser tools are scoped here so they stay on this Agent's explicitly bound
    # browser and never fall back to another Agent/browser instance.
    agent = current_agent()
    try:
        resource = ResourceBindings().require(agent, "browser", ready=True)
    except ResourceAccessError as exc:
        return {"action": "block", "message": f"Hermes Control Center resource policy blocked browser access: {exc}"}
    port = resource.get("debug_port")
    if not port:
        return {"action": "block", "message": "Hermes Control Center resource policy blocked browser access: bound browser has no CDP endpoint"}
    # Hermes resolves BROWSER_CDP_URL before browser.cdp_url. Set it immediately
    # before dispatch so the native browser tool attaches to this Agent's exact
    # bound browser instance instead of launching or selecting another browser.
    os.environ["BROWSER_CDP_URL"] = f"http://127.0.0.1:{int(port)}"
    os.environ["HERMES_CONTROL_CENTER_BROWSER_RESOURCE"] = str(resource.get("id") or "")
    return None
