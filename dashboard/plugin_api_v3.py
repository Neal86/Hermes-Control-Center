from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import ConfigDict, BaseModel, Field

import plugin_api_v2 as base

logger = logging.getLogger("hermes_control_center.api")

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
    logger.info("Control Center API entered: GET /agents/%s", name)
    try:
        data = ManagementCenter().agent_get(name)
        data["tasks"] = TaskCenter().overview(profile=name, include_completed=True)
        logger.info("Control Center API completed: GET /agents/%s", name)
        return data
    except ValueError as exc:
        logger.exception("Control Center API value error: GET /agents/%s", name)
        raise _bad_request(exc) from exc
    except Exception as exc:
        logger.exception("Control Center API failed: GET /agents/%s", name)
        raise _server_error(exc) from exc


@router.post("/agents")
def agent_create(body: AgentBody) -> dict[str, Any]:
    logger.info("Control Center API entered: POST /agents")
    try:
        result = ManagementCenter().agent_create(body.model_dump(exclude_none=True))
        logger.info("Control Center API completed: POST /agents")
        return result
    except ValueError as exc:
        logger.exception("Control Center API value error: POST /agents")
        raise _bad_request(exc) from exc
    except Exception as exc:
        logger.exception("Control Center API failed: POST /agents")
        raise _server_error(exc) from exc


@router.patch("/agents/{name}")
def agent_update(name: str, body: AgentBody) -> dict[str, Any]:
    logger.info("Control Center API entered: PATCH /agents/%s", name)
    try:
        result = ManagementCenter().agent_update(name, body.model_dump(exclude_none=True))
        logger.info("Control Center API completed: PATCH /agents/%s", name)
        return result
    except ValueError as exc:
        logger.exception("Control Center API value error: PATCH /agents/%s", name)
        raise _bad_request(exc) from exc
    except Exception as exc:
        logger.exception("Control Center API failed: PATCH /agents/%s", name)
        raise _server_error(exc) from exc


@router.post("/agents/{name}/action")
def agent_action(name: str, body: AgentActionBody) -> dict[str, Any]:
    logger.info("Control Center API entered: POST /agents/%s/action action=%s", name, body.action)
    try:
        result = ManagementCenter().agent_action(name, body.action, body.value)
        logger.info("Control Center API completed: POST /agents/%s/action action=%s", name, body.action)
        return result
    except ValueError as exc:
        logger.exception("Control Center API value error: POST /agents/%s/action action=%s", name, body.action)
        raise _bad_request(exc) from exc
    except Exception as exc:
        logger.exception("Control Center API failed: POST /agents/%s/action action=%s", name, body.action)
        raise _server_error(exc) from exc


@router.delete("/agents/{name}")
def agent_delete(name: str) -> dict[str, Any]:
    logger.info("Control Center API entered: DELETE /agents/%s", name)
    try:
        result = ManagementCenter().agent_delete(name)
        logger.info("Control Center API completed: DELETE /agents/%s", name)
        return result
    except ValueError as exc:
        logger.exception("Control Center API value error: DELETE /agents/%s", name)
        raise _bad_request(exc) from exc
    except Exception as exc:
        logger.exception("Control Center API failed: DELETE /agents/%s", name)
        raise _server_error(exc) from exc


@router.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def unmatched_plugin_route(path: str, request: Request) -> dict[str, Any]:
    logger.warning(
        "Control Center API unmatched route reached plugin router: method=%s path=/%s full_path=%s",
        request.method,
        path,
        request.url.path,
    )
    raise HTTPException(status_code=404, detail=f"Control Center plugin route not found: {request.method} /{path}")
