from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import ConfigDict, BaseModel, Field

import plugin_api_v2 as base
import extra_api as extra

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


def _agent_get_impl(name: str) -> dict[str, Any]:
    data = ManagementCenter().agent_get(name)
    data["tasks"] = TaskCenter().overview(profile=name, include_completed=True)
    return data


def _agent_update_impl(name: str, body: AgentBody) -> dict[str, Any]:
    return ManagementCenter().agent_update(name, body.model_dump(exclude_none=True))


def _agent_action_impl(name: str, body: AgentActionBody) -> dict[str, Any]:
    return ManagementCenter().agent_action(name, body.action, body.value)


def _agent_delete_impl(name: str) -> dict[str, Any]:
    return ManagementCenter().agent_delete(name)


# Fixed-path compatibility endpoints. Hermes' outer plugin API matcher may reject
# dynamic subpaths before they reach FastAPI, so the Dashboard routes all
# parameterized operations through these stable paths.
@router.get("/agent")
def agent_get_fixed(name: str) -> dict[str, Any]:
    logger.info("Control Center fixed API entered: GET /agent name=%s", name)
    try:
        result = _agent_get_impl(name)
        logger.info("Control Center fixed API completed: GET /agent name=%s", name)
        return result
    except ValueError as exc:
        logger.exception("Control Center fixed API value error: GET /agent name=%s", name)
        raise _bad_request(exc) from exc
    except Exception as exc:
        logger.exception("Control Center fixed API failed: GET /agent name=%s", name)
        raise _server_error(exc) from exc


@router.patch("/agent")
def agent_update_fixed(name: str, body: AgentBody) -> dict[str, Any]:
    logger.info("Control Center fixed API entered: PATCH /agent name=%s", name)
    try:
        return _agent_update_impl(name, body)
    except ValueError as exc:
        logger.exception("Control Center fixed API value error: PATCH /agent name=%s", name)
        raise _bad_request(exc) from exc
    except Exception as exc:
        logger.exception("Control Center fixed API failed: PATCH /agent name=%s", name)
        raise _server_error(exc) from exc


@router.delete("/agent")
def agent_delete_fixed(name: str) -> dict[str, Any]:
    logger.info("Control Center fixed API entered: DELETE /agent name=%s", name)
    try:
        return _agent_delete_impl(name)
    except ValueError as exc:
        logger.exception("Control Center fixed API value error: DELETE /agent name=%s", name)
        raise _bad_request(exc) from exc
    except Exception as exc:
        logger.exception("Control Center fixed API failed: DELETE /agent name=%s", name)
        raise _server_error(exc) from exc


@router.post("/agent/action")
def agent_action_fixed(name: str, body: AgentActionBody) -> dict[str, Any]:
    logger.info("Control Center fixed API entered: POST /agent/action name=%s action=%s", name, body.action)
    try:
        return _agent_action_impl(name, body)
    except ValueError as exc:
        logger.exception("Control Center fixed API value error: POST /agent/action name=%s action=%s", name, body.action)
        raise _bad_request(exc) from exc
    except Exception as exc:
        logger.exception("Control Center fixed API failed: POST /agent/action name=%s action=%s", name, body.action)
        raise _server_error(exc) from exc


@router.put("/provider")
def provider_save_fixed(provider: str, body: base.ProviderBody, profile: str = "default") -> dict[str, Any]:
    logger.info("Control Center fixed API entered: PUT /provider provider=%s profile=%s", provider, profile)
    return base.provider_save(provider, body, profile)


@router.post("/resource/bind")
def resource_bind_fixed(resource_id: str, body: extra.BindingBody) -> dict[str, Any]:
    logger.info("Control Center fixed API entered: POST /resource/bind resource_id=%s agent=%s", resource_id, body.agent)
    return extra.bind_resource(resource_id, body)


@router.delete("/resource/bind")
def resource_unbind_fixed(resource_id: str) -> dict[str, Any]:
    logger.info("Control Center fixed API entered: DELETE /resource/bind resource_id=%s", resource_id)
    return extra.unbind_resource(resource_id)


@router.get("/agent/resources")
def agent_resources_fixed(agent: str, refresh: bool = True) -> dict[str, Any]:
    logger.info("Control Center fixed API entered: GET /agent/resources agent=%s", agent)
    return extra.agent_resources(agent, refresh)


@router.get("/agent/browser")
def agent_browser_fixed(agent: str) -> dict[str, Any]:
    logger.info("Control Center fixed API entered: GET /agent/browser agent=%s", agent)
    return extra.agent_browser(agent)


@router.get("/agent/wechat/status")
def agent_wechat_status_fixed(agent: str, resource_id: str | None = None) -> dict[str, Any]:
    logger.info("Control Center fixed API entered: GET /agent/wechat/status agent=%s", agent)
    return extra.bound_wechat_status(agent, resource_id)


@router.post("/agent/wechat/dry-run")
def agent_wechat_dry_run_fixed(agent: str, body: extra.WeChatBoundDryRunBody) -> dict[str, Any]:
    logger.info("Control Center fixed API entered: POST /agent/wechat/dry-run agent=%s", agent)
    return extra.bound_wechat_dry_run(agent, body)


# Keep the original dynamic routes for newer Hermes versions and direct FastAPI use.
@router.get("/agents/{name}")
def agent_get(name: str) -> dict[str, Any]:
    logger.info("Control Center API entered: GET /agents/%s", name)
    try:
        data = _agent_get_impl(name)
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
        result = _agent_update_impl(name, body)
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
        result = _agent_action_impl(name, body)
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
        result = _agent_delete_impl(name)
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
