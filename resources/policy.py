from __future__ import annotations

import os
from typing import Any

from .bindings import ResourceAccessError, ResourceBindings
from .context import current_agent

_BROWSER_PREFIXES = ("browser_",)
_BROWSER_NAMES = {"browser", "browser_exec", "browser_cdp"}
_COMPUTER_USE_NAMES = {"computer_use", "computer", "computer_control"}


def _is_browser_tool(name: str) -> bool:
    value = str(name or "").strip()
    return value in _BROWSER_NAMES or any(value.startswith(prefix) for prefix in _BROWSER_PREFIXES)


def _is_computer_use_tool(name: str) -> bool:
    return str(name or "").strip().lower() in _COMPUTER_USE_NAMES


def _agent_has_bound_wechat(agent: str) -> bool:
    try:
        ResourceBindings().require(agent, "wechat", ready=True)
        return True
    except ResourceAccessError:
        return False


def pre_tool_call(tool_name: str, args: dict[str, Any], task_id: str = "", **kwargs):
    del args, task_id, kwargs
    agent = current_agent()

    # A WeChat-bound customer-service Agent has exactly one outbound WeChat path:
    # the bound wechat_desktop Gateway adapter. Generic computer_use can otherwise
    # attach to another Weixin.exe window (or its sticky desktop target) and send
    # a second reply from the wrong account. For a WeChat-bound Agent, block the
    # generic desktop surface entirely; browser work remains available through
    # the exact Agent-bound browser tools below.
    if _is_computer_use_tool(tool_name) and _agent_has_bound_wechat(agent):
        return {
            "action": "block",
            "message": (
                "Hermes Control Center blocked computer_use for this WeChat-bound Agent. "
                "Do not operate WeChat/Weixin directly. Return the reply text and let the bound "
                "wechat_desktop Gateway deliver it to the source conversation. Use the bound "
                "browser tools for web lookups."
            ),
        }

    if not _is_browser_tool(tool_name):
        return None
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
