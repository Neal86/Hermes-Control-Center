from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

DASHBOARD_ROOT = Path(__file__).resolve().parent
PLUGIN_ROOT = DASHBOARD_ROOT.parent
if str(DASHBOARD_ROOT) not in sys.path:
    sys.path.insert(0, str(DASHBOARD_ROOT))
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from backend_packages_v2 import load_module  # noqa: E402

ManagementCenter = load_module("hcc_management", "management", "service").ManagementCenter
_bindings_module = load_module("hcc_resources", "resources", "bindings")
ResourceBindings = _bindings_module.ResourceBindings
ResourceRegistry = load_module("hcc_resources", "resources", "registry").ResourceRegistry
_browser_module = load_module("hcc_resources", "resources", "browser_manager")
launch_managed_browser = _browser_module.launch_managed_browser
import_existing_browser_to_cdp = _browser_module.import_existing_browser_to_cdp
browser_diagnostic_log_path = _browser_module.browser_diagnostic_log_path

router = APIRouter()


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ManagedBrowserBody(StrictBody):
    agent: str = Field(min_length=1, max_length=64)
    browser: Literal["chrome", "edge"] = "chrome"
    start_url: str = Field(default="https://wx.qq.com/", min_length=1, max_length=4096)


class ImportBrowserBody(StrictBody):
    agent: str = Field(min_length=1, max_length=64)
    start_url: str = Field(default="https://wx.qq.com/", min_length=1, max_length=4096)


def _known_agents() -> set[str]:
    return {
        str(row.get("name") or "").strip().lower()
        for row in ManagementCenter().agent_list(probe_runtime=False)
        if str(row.get("name") or "").strip()
    }


def _bind_launched_browser(agent: str, launch: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    port = int(launch["debug_port"])
    user_data_dir = str(launch.get("user_data_dir") or "").lower()
    resource = None
    registry = ResourceRegistry()
    for _ in range(16):
        rows = registry.list(refresh=True)
        resource = next(
            (
                row
                for row in rows
                if row.get("kind") == "browser"
                and int(row.get("debug_port") or 0) == port
                and (
                    not user_data_dir
                    or str(row.get("user_data_dir") or "").lower() == user_data_dir
                )
            ),
            None,
        )
        if resource is not None:
            break
        time.sleep(0.25)
    if resource is None:
        raise RuntimeError(
            "managed browser CDP is ready but resource discovery did not find the browser process"
        )
    binding = ResourceBindings().bind(str(resource["id"]), agent)
    return resource, binding


def _restart_gateway(agent: str, resource: dict[str, Any]) -> dict[str, Any]:
    """Reload tool availability after a browser/CDP binding changes."""
    port = int(resource.get("debug_port") or 0)
    if port <= 0:
        raise RuntimeError("Bound browser has no usable CDP port")
    management = ManagementCenter()
    cdp_url = f"http://127.0.0.1:{port}"
    management._set_config(agent, "browser.cdp_url", cdp_url)
    result = management.agent_action(agent, "gateway_restart")
    if not result.get("ok"):
        raise RuntimeError(str(result.get("warning") or "Gateway restart could not be verified"))
    return dict(result, cdp_url=cdp_url)


@router.post("/resources/browser/launch")
def launch_agent_browser(body: ManagedBrowserBody) -> dict[str, Any]:
    agent = body.agent.strip().lower()
    if agent not in _known_agents():
        raise HTTPException(status_code=400, detail="unknown agent")
    try:
        launch = launch_managed_browser(
            agent,
            browser=body.browser,
            start_url=body.start_url,
        )
        resource, binding = _bind_launched_browser(agent, launch)
        gateway_restart = _restart_gateway(agent, resource)
        return {
            "ok": True,
            "launch": launch,
            "resource": dict(resource, assigned_agent=agent),
            "binding": binding,
            "gateway_restart": gateway_restart,
            "diagnostic_log": browser_diagnostic_log_path(),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/resources/browser/{resource_id}/import-cdp")
def import_existing_browser(resource_id: str, body: ImportBrowserBody) -> dict[str, Any]:
    agent = body.agent.strip().lower()
    if agent not in _known_agents():
        raise HTTPException(status_code=400, detail="unknown agent")
    try:
        resource = ResourceRegistry().get(resource_id, refresh=True)
        if resource is None:
            raise ValueError("unknown browser resource")
        result = import_existing_browser_to_cdp(
            resource,
            agent,
            start_url=body.start_url,
        )
        launch = dict(result.get("launch") or {})
        managed_resource, binding = _bind_launched_browser(agent, launch)
        gateway_restart = _restart_gateway(agent, managed_resource)
        return {
            "ok": True,
            "import": result,
            "launch": launch,
            "resource": dict(managed_resource, assigned_agent=agent),
            "binding": binding,
            "gateway_restart": gateway_restart,
            "diagnostic_log": browser_diagnostic_log_path(),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/resources/browser/diagnostics")
def browser_diagnostics() -> dict[str, Any]:
    rows = ResourceRegistry().list(refresh=True)
    browsers = [
        {
            "id": row.get("id"),
            "app": row.get("app"),
            "pid": row.get("pid"),
            "title": row.get("title"),
            "profile": row.get("profile"),
            "debug_port": row.get("debug_port"),
            "attachable": bool(row.get("attachable")),
            "attach_reason": row.get("attach_reason"),
            "attach_error": row.get("attach_error"),
        }
        for row in rows
        if row.get("kind") == "browser" and row.get("online")
    ]
    return {
        "items": browsers,
        "diagnostic_log": browser_diagnostic_log_path(),
        "hint": (
            "Normal already-running Chrome/Edge cannot gain CDP in-place. "
            "Use import-cdp to snapshot its logged-in profile into an Agent-owned "
            "CDP profile, or launch a fresh managed browser."
        ),
    }
