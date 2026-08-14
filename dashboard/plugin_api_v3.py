from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import ConfigDict, BaseModel, Field

import plugin_api_v2 as base

router = APIRouter()
router.include_router(base.router)
ManagementCenter = base.ManagementCenter
TaskCenter = base.TaskCenter


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AgentBody(StrictBody):
    name: str | None = Field(default=None, max_length=64)
    description: str | None = Field(default=None, max_length=2000)
    clone_mode: Literal["blank", "clone", "clone_all"] | None = None
    clone_from: str | None = Field(default=None, max_length=64)
    no_skills: bool | None = None
    workspace: str | None = Field(default=None, max_length=4096)
    model: str | None = Field(default=None, max_length=512)
    provider: str | None = Field(default=None, max_length=128)
    soul: str | None = Field(default=None, max_length=200000)


class AgentActionBody(StrictBody):
    action: Literal[
        "use",
        "gateway_start",
        "gateway_stop",
        "gateway_restart",
        "gateway_status",
        "set_workspace",
        "export",
    ]
    value: str | None = Field(default=None, max_length=4096)


def _bad_request(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


def _server_error(exc: Exception) -> HTTPException:
    return HTTPException(status_code=500, detail=str(exc))


@router.get("/agents/{name}")
def agent_get(name: str) -> dict[str, Any]:
    try:
        data = ManagementCenter().agent_get(name)
        data["tasks"] = TaskCenter().overview(profile=name, include_completed=True)
        return data
    except ValueError as exc:
        raise _bad_request(exc) from exc
    except Exception as exc:
        raise _server_error(exc) from exc


@router.post("/agents")
def agent_create(body: AgentBody) -> dict[str, Any]:
    try:
        return ManagementCenter().agent_create(body.model_dump(exclude_none=True))
    except ValueError as exc:
        raise _bad_request(exc) from exc
    except Exception as exc:
        raise _server_error(exc) from exc


@router.patch("/agents/{name}")
def agent_update(name: str, body: AgentBody) -> dict[str, Any]:
    try:
        return ManagementCenter().agent_update(name, body.model_dump(exclude_none=True))
    except ValueError as exc:
        raise _bad_request(exc) from exc
    except Exception as exc:
        raise _server_error(exc) from exc


@router.post("/agents/{name}/action")
def agent_action(name: str, body: AgentActionBody) -> dict[str, Any]:
    try:
        return ManagementCenter().agent_action(name, body.action, body.value)
    except ValueError as exc:
        raise _bad_request(exc) from exc
    except Exception as exc:
        raise _server_error(exc) from exc


@router.delete("/agents/{name}")
def agent_delete(name: str) -> dict[str, Any]:
    try:
        return ManagementCenter().agent_delete(name)
    except ValueError as exc:
        raise _bad_request(exc) from exc
    except Exception as exc:
        raise _server_error(exc) from exc
