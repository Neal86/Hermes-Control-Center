from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from management.service import ManagementCenter  # noqa: E402
from providers.service import ProviderService  # noqa: E402
from resources.bindings import ResourceAccessError, ResourceBindings  # noqa: E402
from resources.registry import ResourceRegistry  # noqa: E402
from resources.wechat_bound import BoundWeChatDesktop  # noqa: E402

router = APIRouter()


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BindingBody(StrictBody):
    agent: str = Field(min_length=1, max_length=64)


class ProviderBody(StrictBody):
    api_key: str | None = Field(default=None, max_length=8192)
    clear_api_key: bool = False
    base_url: str | None = Field(default=None, max_length=4096)
    default_model: str | None = Field(default=None, max_length=512)
    configured: bool | None = None
    oauth_status: str | None = Field(default=None, max_length=128)


class WeChatBoundDryRunBody(StrictBody):
    agent: str = Field(min_length=1, max_length=64)
    resource_id: str | None = Field(default=None, max_length=128)
    chat: str = Field(min_length=1, max_length=256)
    text: str = Field(min_length=1, max_length=4000)


def _bad(exc: Exception) -> HTTPException:
    code = 409 if isinstance(exc, ResourceAccessError) else 400
    return HTTPException(status_code=code, detail=str(exc))


@router.get("/resources")
def resources(refresh: bool = False) -> dict[str, Any]:
    try:
        bindings = ResourceBindings()
        assigned = bindings.list()
        rows = ResourceRegistry().list(refresh=refresh)
        return {
            "items": [dict(row, assigned_agent=assigned.get(str(row.get("id")))) for row in rows],
            "bindings": assigned,
            "agents": [row["name"] for row in ManagementCenter().agent_list(probe_runtime=False)],
            "policy": {"fail_closed": True, "fallback": False, "exclusive_resource_owner": True},
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/resources/{resource_id}/bind")
def bind_resource(resource_id: str, body: BindingBody) -> dict[str, Any]:
    try:
        known = {row["name"] for row in ManagementCenter().agent_list(probe_runtime=False)}
        if body.agent not in known:
            raise ValueError("unknown agent")
        return ResourceBindings().bind(resource_id, body.agent)
    except Exception as exc:
        raise _bad(exc) from exc


@router.delete("/resources/{resource_id}/bind")
def unbind_resource(resource_id: str) -> dict[str, Any]:
    try:
        return {"ok": True, "unbound": ResourceBindings().unbind(resource_id)}
    except Exception as exc:
        raise _bad(exc) from exc


@router.get("/agents/{agent}/resources")
def agent_resources(agent: str, refresh: bool = True) -> dict[str, Any]:
    try:
        return {"items": ResourceBindings().resources_for_agent(agent, refresh=refresh), "fail_closed": True}
    except Exception as exc:
        raise _bad(exc) from exc


@router.get("/agents/{agent}/browser")
def agent_browser(agent: str) -> dict[str, Any]:
    try:
        resource = ResourceBindings().require(agent, "browser", ready=True)
        return {
            "resource": resource,
            "cdp_url": f"http://127.0.0.1:{resource['debug_port']}" if resource.get("debug_port") else None,
            "policy": "bound-only",
        }
    except Exception as exc:
        raise _bad(exc) from exc


@router.get("/agents/{agent}/wechat/status")
def bound_wechat_status(agent: str, resource_id: str | None = None) -> dict[str, Any]:
    try:
        return BoundWeChatDesktop(agent, resource_id).status()
    except Exception as exc:
        raise _bad(exc) from exc


@router.post("/agents/{agent}/wechat/dry-run")
def bound_wechat_dry_run(agent: str, body: WeChatBoundDryRunBody) -> dict[str, Any]:
    if body.agent != agent:
        raise HTTPException(status_code=400, detail="agent mismatch")
    try:
        return BoundWeChatDesktop(agent, body.resource_id).send_message(body.chat, body.text, dry_run=True)
    except Exception as exc:
        raise _bad(exc) from exc


@router.get("/providers")
def providers(profile: str = "default") -> dict[str, Any]:
    try:
        service = ProviderService()
        return {"profile": profile, "items": service.list(profile), "catalog": service.catalog()}
    except Exception as exc:
        raise _bad(exc) from exc


@router.put("/providers/{provider}")
def provider_save(provider: str, body: ProviderBody, profile: str = "default") -> dict[str, Any]:
    try:
        return ProviderService().save(profile, provider, body.model_dump(exclude_none=True))
    except Exception as exc:
        raise _bad(exc) from exc
