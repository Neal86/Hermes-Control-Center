from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import ConfigDict, BaseModel, Field

import plugin_api_v2 as base
import extra_api as extra
import browser_api

# Use Hermes' native dashboard logger so all Control Center request diagnostics
# and tracebacks appear in the built-in Logs -> AGENT.LOG view.
logger = logging.getLogger("hermes_cli.web_server")

router = APIRouter()
# Browser routes must be registered before the base router because the base
# compatibility API ends with a catch-all plugin route.
router.include_router(browser_api.router)
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


@router.get("/agent")
def agent_get_fixed(name: str) -> dict[str, Any]:
    logger.info("[ControlCenter] request entered: GET /agent name=%s", name)
    try:
        result = _agent_get_impl(name)
        logger.info("[ControlCenter] request completed: GET /agent name=%s", name)
        return result
    except ValueError as exc:
        logger.exception("[ControlCenter] request value error: GET /agent name=%s", name)
        raise _bad_request(exc) from exc
    except Exception as exc:
        logger.exception("[ControlCenter] request failed: GET /agent name=%s", name)
        raise _server_error(exc) from exc


@router.patch("/agent")
def agent_update_fixed(name: str, body: AgentBody) -> dict[str, Any]:
    logger.info("[ControlCenter] request entered: PATCH /agent name=%s", name)
    try:
        result = _agent_update_impl(name, body)
        logger.info("[ControlCenter] request completed: PATCH /agent name=%s", name)
        return result
    except ValueError as exc:
        logger.exception("[ControlCenter] request value error: PATCH /agent name=%s", name)
        raise _bad_request(exc) from exc
    except Exception as exc:
        logger.exception("[ControlCenter] request failed: PATCH /agent name=%s", name)
        raise _server_error(exc) from exc


@router.delete("/agent")
def agent_delete_fixed(name: str) -> dict[str, Any]:
    logger.info("[ControlCenter] request entered: DELETE /agent name=%s", name)
    try:
        result = _agent_delete_impl(name)
        logger.info("[ControlCenter] request completed: DELETE /agent name=%s", name)
        return result
    except ValueError as exc:
        logger.exception("[ControlCenter] request value error: DELETE /agent name=%s", name)
        raise _bad_request(exc) from exc
    except Exception as exc:
        logger.exception("[ControlCenter] request failed: DELETE /agent name=%s", name)
        raise _server_error(exc) from exc


@router.post("/agent/action")
def agent_action_fixed(name: str, body: AgentActionBody) -> dict[str, Any]:
    logger.info("[ControlCenter] request entered: POST /agent/action name=%s action=%s", name, body.action)
    try:
        result = _agent_action_impl(name, body)
        logger.info("[ControlCenter] request completed: POST /agent/action name=%s action=%s", name, body.action)
        return result
    except ValueError as exc:
        logger.exception("[ControlCenter] request value error: POST /agent/action name=%s action=%s", name, body.action)
        raise _bad_request(exc) from exc
    except Exception as exc:
        logger.exception("[ControlCenter] request failed: POST /agent/action name=%s action=%s", name, body.action)
        raise _server_error(exc) from exc


@router.put("/provider")
def provider_save_fixed(provider: str, body: base.ProviderBody, profile: str = "default") -> dict[str, Any]:
    logger.info("[ControlCenter] request entered: PUT /provider provider=%s profile=%s", provider, profile)
    try:
        result = base.provider_save(provider, body, profile)
        logger.info("[ControlCenter] request completed: PUT /provider provider=%s profile=%s", provider, profile)
        return result
    except Exception:
        logger.exception("[ControlCenter] request failed: PUT /provider provider=%s profile=%s", provider, profile)
        raise


@router.post("/resource/bind")
def resource_bind_fixed(resource_id: str, body: extra.BindingBody) -> dict[str, Any]:
    logger.info("[ControlCenter] request entered: POST /resource/bind resource_id=%s agent=%s", resource_id, body.agent)
    try:
        result = extra.bind_resource(resource_id, body)
        logger.info("[ControlCenter] request completed: POST /resource/bind resource_id=%s", resource_id)
        return result
    except Exception:
        logger.exception("[ControlCenter] request failed: POST /resource/bind resource_id=%s", resource_id)
        raise


@router.delete("/resource/bind")
def resource_unbind_fixed(resource_id: str) -> dict[str, Any]:
    logger.info("[ControlCenter] request entered: DELETE /resource/bind resource_id=%s", resource_id)
    try:
        result = extra.unbind_resource(resource_id)
        logger.info("[ControlCenter] request completed: DELETE /resource/bind resource_id=%s", resource_id)
        return result
    except Exception:
        logger.exception("[ControlCenter] request failed: DELETE /resource/bind resource_id=%s", resource_id)
        raise


@router.post("/resource/focus")
def resource_focus_fixed(resource_id: str) -> dict[str, Any]:
    logger.info("[ControlCenter] request entered: POST /resource/focus resource_id=%s", resource_id)
    try:
        result = extra.focus_resource(resource_id)
        logger.info("[ControlCenter] request completed: POST /resource/focus resource_id=%s", resource_id)
        return result
    except Exception:
        logger.exception("[ControlCenter] request failed: POST /resource/focus resource_id=%s", resource_id)
        raise


@router.get("/agent/resources")
def agent_resources_fixed(agent: str, refresh: bool = True) -> dict[str, Any]:
    logger.info("[ControlCenter] request entered: GET /agent/resources agent=%s refresh=%s", agent, refresh)
    try:
        result = extra.agent_resources(agent, refresh)
        logger.info("[ControlCenter] request completed: GET /agent/resources agent=%s", agent)
        return result
    except Exception:
        logger.exception("[ControlCenter] request failed: GET /agent/resources agent=%s", agent)
        raise


@router.get("/agent/browser")
def agent_browser_fixed(agent: str) -> dict[str, Any]:
    logger.info("[ControlCenter] request entered: GET /agent/browser agent=%s", agent)
    try:
        result = extra.agent_browser(agent)
        logger.info("[ControlCenter] request completed: GET /agent/browser agent=%s", agent)
        return result
    except Exception:
        logger.exception("[ControlCenter] request failed: GET /agent/browser agent=%s", agent)
        raise


@router.get("/agent/wechat/status")
def agent_wechat_status_fixed(agent: str, resource_id: str | None = None) -> dict[str, Any]:
    logger.info("[ControlCenter] request entered: GET /agent/wechat/status agent=%s resource_id=%s", agent, resource_id)
    try:
        result = extra.bound_wechat_status(agent, resource_id)
        logger.info("[ControlCenter] request completed: GET /agent/wechat/status agent=%s", agent)
        return result
    except Exception:
        logger.exception("[ControlCenter] request failed: GET /agent/wechat/status agent=%s", agent)
        raise


@router.post("/agent/wechat/dry-run")
def agent_wechat_dry_run_fixed(agent: str, body: extra.WeChatBoundDryRunBody) -> dict[str, Any]:
    logger.info("[ControlCenter] request entered: POST /agent/wechat/dry-run agent=%s", agent)
    try:
        result = extra.bound_wechat_dry_run(agent, body)
        logger.info("[ControlCenter] request completed: POST /agent/wechat/dry-run agent=%s", agent)
        return result
    except Exception:
        logger.exception("[ControlCenter] request failed: POST /agent/wechat/dry-run agent=%s", agent)
        raise


@router.get("/agents/{name}")
def agent_get(name: str) -> dict[str, Any]:
    logger.info("[ControlCenter] request entered: GET /agents/%s", name)
    try:
        result = _agent_get_impl(name)
        logger.info("[ControlCenter] request completed: GET /agents/%s", name)
        return result
    except ValueError as exc:
        logger.exception("[ControlCenter] request value error: GET /agents/%s", name)
        raise _bad_request(exc) from exc
    except Exception as exc:
        logger.exception("[ControlCenter] request failed: GET /agents/%s", name)
        raise _server_error(exc) from exc


@router.post("/agents")
def agent_create(body: AgentBody) -> dict[str, Any]:
    logger.info("[ControlCenter] request entered: POST /agents")
    try:
        result = ManagementCenter().agent_create(body.model_dump(exclude_none=True))
        logger.info("[ControlCenter] request completed: POST /agents")
        return result
    except ValueError as exc:
        logger.exception("[ControlCenter] request value error: POST /agents")
        raise _bad_request(exc) from exc
    except Exception as exc:
        logger.exception("[ControlCenter] request failed: POST /agents")
        raise _server_error(exc) from exc


@router.patch("/agents/{name}")
def agent_update(name: str, body: AgentBody) -> dict[str, Any]:
    logger.info("[ControlCenter] request entered: PATCH /agents/%s", name)
    try:
        result = _agent_update_impl(name, body)
        logger.info("[ControlCenter] request completed: PATCH /agents/%s", name)
        return result
    except ValueError as exc:
        logger.exception("[ControlCenter] request value error: PATCH /agents/%s", name)
        raise _bad_request(exc) from exc
    except Exception as exc:
        logger.exception("[ControlCenter] request failed: PATCH /agents/%s", name)
        raise _server_error(exc) from exc


@router.post("/agents/{name}/action")
def agent_action(name: str, body: AgentActionBody) -> dict[str, Any]:
    logger.info("[ControlCenter] request entered: POST /agents/%s/action action=%s", name, body.action)
    try:
        result = _agent_action_impl(name, body)
        logger.info("[ControlCenter] request completed: POST /agents/%s/action action=%s", name, body.action)
        return result
    except ValueError as exc:
        logger.exception("[ControlCenter] request value error: POST /agents/%s/action action=%s", name, body.action)
        raise _bad_request(exc) from exc
    except Exception as exc:
        logger.exception("[ControlCenter] request failed: POST /agents/%s/action action=%s", name, body.action)
        raise _server_error(exc) from exc


@router.delete("/agents/{name}")
def agent_delete(name: str) -> dict[str, Any]:
    logger.info("[ControlCenter] request entered: DELETE /agents/%s", name)
    try:
        result = _agent_delete_impl(name)
        logger.info("[ControlCenter] request completed: DELETE /agents/%s", name)
        return result
    except ValueError as exc:
        logger.exception("[ControlCenter] request value error: DELETE /agents/%s", name)
        raise _bad_request(exc) from exc
    except Exception as exc:
        logger.exception("[ControlCenter] request failed: DELETE /agents/%s", name)
        raise _server_error(exc) from exc


@router.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def unmatched_plugin_route(path: str, request: Request) -> dict[str, Any]:
    logger.warning(
        "[ControlCenter] unmatched plugin route: method=%s path=/%s full_path=%s query=%s",
        request.method,
        path,
        request.url.path,
        request.url.query,
    )
    raise HTTPException(status_code=404, detail=f"Control Center plugin route not found: {request.method} /{path}")
