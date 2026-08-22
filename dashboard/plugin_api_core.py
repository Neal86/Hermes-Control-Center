from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))


def _load_module(relative: str, module_name: str):
    path = PLUGIN_ROOT / relative
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module


TaskCenter = _load_module(
    "task_center/service_v3.py", "hermes_extensions_task_center_service"
).TaskCenter
ManagementCenter = _load_module(
    "management/service.py", "hermes_extensions_management_service"
).ManagementCenter
gateway_lifecycle = _load_module(
    "hcc_gateway/lifecycle.py", "hermes_extensions_dashboard_gateway_lifecycle"
)
gateway_lifecycle.install_independent_gateway_policy(ManagementCenter)
WeChatDesktop = _load_module(
    "wechat/runtime.py", "hermes_extensions_dashboard_wechat_runtime"
).WeChatDesktop
compat = _load_module("compatibility.py", "hermes_extensions_compatibility")
overview_module = _load_module(
    "management/overview.py", "hermes_extensions_management_overview"
)
build_management_overview = overview_module.build_management_overview
router = APIRouter()


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TaskBody(StrictBody):
    type: Literal["cron", "kanban"] | None = None
    name: str | None = Field(default=None, max_length=256)
    prompt: str | None = Field(default=None, max_length=20000)
    schedule: str | None = Field(default=None, max_length=256)
    profile: str | None = Field(default=None, max_length=64)
    priority: int | None = Field(default=None, ge=0, le=100)
    deliver: str | None = Field(default=None, max_length=128)


class TaskActionBody(StrictBody):
    action: Literal["pause", "resume", "run", "remove", "assign", "archive"]
    value: str | None = Field(default=None, max_length=4096)
    profile: str | None = Field(default=None, max_length=64)


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


class ProjectBody(StrictBody):
    name: str | None = Field(default=None, max_length=256)
    profile: str | None = Field(default=None, max_length=64)
    slug: str | None = Field(default=None, max_length=128)
    folders: list[str] | None = Field(default=None, max_length=64)
    primary: str | None = Field(default=None, max_length=4096)
    description: str | None = Field(default=None, max_length=2000)
    icon: str | None = Field(default=None, max_length=128)
    color: str | None = Field(default=None, max_length=64)
    board: str | None = Field(default=None, max_length=128)
    use: bool | None = None
    agent: str | None = Field(default=None, max_length=64)
    add_folders: list[str] | None = Field(default=None, max_length=64)
    remove_folders: list[str] | None = Field(default=None, max_length=64)


class ProjectActionBody(StrictBody):
    action: Literal[
        "use",
        "archive",
        "restore",
        "add_folder",
        "remove_folder",
        "set_primary",
        "bind_board",
        "assign_agent",
    ]
    value: str | None = Field(default=None, max_length=4096)
    profile: str | None = Field(default=None, max_length=64)


class WeChatDryRunBody(StrictBody):
    chat: str = Field(min_length=1, max_length=256)
    text: str = Field(min_length=1, max_length=4000)


def _bad_request(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


def _server_error(exc: Exception) -> HTTPException:
    return HTTPException(status_code=500, detail=str(exc))


def _caps(*, force: bool = False):
    return compat.detect_capabilities(force=force)


def _unsupported_project() -> dict[str, Any]:
    payload = compat.project_unavailable_payload()
    payload["capabilities"] = _caps().to_dict()
    return payload


def _project_required() -> None:
    if not _caps().project:
        raise HTTPException(status_code=409, detail=_unsupported_project())


def _wechat_health() -> dict[str, Any]:
    hermes_home = Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")
    path = hermes_home / "plugin-data" / "hermes-extensions" / "wechat" / "gateway-health.json"
    if not path.exists():
        return {
            "status": "unknown",
            "consecutive_failures": 0,
            "last_error": None,
            "last_success_at": None,
            "updated_at": None,
        }
    try:
        data = json.loads(path.read_text("utf-8"))
        return data if isinstance(data, dict) else {"status": "unknown"}
    except Exception as exc:
        return {"status": "unknown", "last_error": f"Unable to read gateway health: {exc}"}


@router.get("/capabilities")
def capabilities(refresh: bool = False) -> dict[str, Any]:
    caps = _caps(force=refresh)
    return {"capabilities": caps.to_dict(), "project_supported": caps.project}


@router.get("/overview")
def overview(profile: str | None = None, include_completed: bool = False) -> dict[str, Any]:
    try:
        return TaskCenter().overview(profile=profile, include_completed=include_completed)
    except Exception as exc:
        raise _server_error(exc) from exc


@router.get("/upcoming")
def upcoming(
    hours: int = Query(168, ge=1, le=2160),
    profile: str | None = None,
    limit: int = Query(300, ge=1, le=1000),
) -> dict[str, Any]:
    try:
        return {"items": TaskCenter().upcoming(hours=hours, profile=profile, limit=limit)}
    except Exception as exc:
        raise _server_error(exc) from exc


@router.post("/tasks")
def create_task(body: TaskBody) -> dict[str, Any]:
    payload = body.model_dump(exclude_none=True)
    if not payload.get("type"):
        raise HTTPException(status_code=400, detail="type is required")
    try:
        return TaskCenter().create(payload)
    except ValueError as exc:
        raise _bad_request(exc) from exc
    except Exception as exc:
        raise _server_error(exc) from exc


@router.patch("/tasks/{task_type}/{task_id}")
def update_task(
    task_type: Literal["cron", "kanban"], task_id: str, body: TaskBody
) -> dict[str, Any]:
    payload = body.model_dump(exclude_none=True)
    payload.update({"type": task_type, "id": task_id})
    try:
        return TaskCenter().update(payload)
    except ValueError as exc:
        raise _bad_request(exc) from exc
    except Exception as exc:
        raise _server_error(exc) from exc


@router.post("/tasks/{task_type}/{task_id}/action")
def task_action(
    task_type: Literal["cron", "kanban"], task_id: str, body: TaskActionBody
) -> dict[str, Any]:
    payload: dict[str, Any] = {"type": task_type, "id": task_id, "action": body.action}
    if body.value is not None:
        payload["value"] = body.value
    if body.profile is not None:
        payload["profile"] = body.profile
    try:
        return TaskCenter().action(payload)
    except ValueError as exc:
        raise _bad_request(exc) from exc
    except Exception as exc:
        raise _server_error(exc) from exc


@router.get("/tasks/{task_type}/{task_id}/history")
def history(
    task_type: Literal["cron", "kanban"],
    task_id: str,
    profile: str | None = None,
    limit: int = Query(20, ge=1, le=200),
) -> dict[str, Any]:
    try:
        return {"items": TaskCenter().history(task_type, task_id, limit=limit, profile=profile)}
    except ValueError as exc:
        raise _bad_request(exc) from exc
    except Exception as exc:
        raise _server_error(exc) from exc


@router.get("/management/overview")
def management_overview() -> dict[str, Any]:
    try:
        return build_management_overview()
    except Exception as exc:
        raise _server_error(exc) from exc


@router.get("/wechat/health")
def wechat_health() -> dict[str, Any]:
    return _wechat_health()


@router.get("/wechat/status")
def wechat_status() -> dict[str, Any]:
    try:
        return WeChatDesktop().status()
    except Exception as exc:
        raise _server_error(exc) from exc


@router.get("/wechat/chats")
def wechat_chats(limit: int = Query(30, ge=1, le=200)) -> dict[str, Any]:
    try:
        return {"items": [row.to_dict() for row in WeChatDesktop().list_chats(limit)]}
    except Exception as exc:
        raise _server_error(exc) from exc


@router.get("/wechat/unread")
def wechat_unread(limit: int = Query(30, ge=1, le=200)) -> dict[str, Any]:
    try:
        return {"items": [row.to_dict() for row in WeChatDesktop().unread_chats(limit)]}
    except Exception as exc:
        raise _server_error(exc) from exc


@router.post("/wechat/dry-run")
def wechat_dry_run(body: WeChatDryRunBody) -> dict[str, Any]:
    try:
        return WeChatDesktop().send_message(body.chat, body.text, dry_run=True)
    except ValueError as exc:
        raise _bad_request(exc) from exc
    except Exception as exc:
        raise _server_error(exc) from exc


@router.get("/agents")
def agents() -> dict[str, Any]:
    try:
        return {"items": ManagementCenter().agent_list()}
    except Exception as exc:
        raise _server_error(exc) from exc


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


@router.get("/projects")
def projects(profile: str | None = None, include_archived: bool = True) -> dict[str, Any]:
    if not _caps().project:
        return _unsupported_project()
    try:
        center = ManagementCenter()
        if profile:
            return {
                "supported": True,
                "items": center.project_list(profile, include_archived=include_archived),
                "partial": False,
                "errors": [],
            }
        snapshot = center.snapshot(include_archived=include_archived)
        return {
            "supported": True,
            "items": snapshot["projects"],
            "partial": snapshot["partial"],
            "errors": snapshot["errors"],
        }
    except ValueError as exc:
        raise _bad_request(exc) from exc
    except Exception as exc:
        raise _server_error(exc) from exc


@router.get("/projects/{project}")
def project_get(project: str, profile: str = "default") -> dict[str, Any]:
    if not _caps().project:
        return _unsupported_project()
    try:
        return ManagementCenter().project_get(project, profile)
    except ValueError as exc:
        raise _bad_request(exc) from exc
    except Exception as exc:
        raise _server_error(exc) from exc


@router.post("/projects")
def project_create(body: ProjectBody) -> dict[str, Any]:
    _project_required()
    try:
        return ManagementCenter().project_create(body.model_dump(exclude_none=True))
    except ValueError as exc:
        raise _bad_request(exc) from exc
    except Exception as exc:
        raise _server_error(exc) from exc


@router.patch("/projects/{project}")
def project_update(project: str, body: ProjectBody) -> dict[str, Any]:
    _project_required()
    payload = body.model_dump(exclude_none=True)
    profile = str(payload.pop("profile", "default"))
    try:
        return ManagementCenter().project_update(project, profile, payload)
    except ValueError as exc:
        raise _bad_request(exc) from exc
    except Exception as exc:
        raise _server_error(exc) from exc


@router.post("/projects/{project}/action")
def project_action(project: str, body: ProjectActionBody) -> dict[str, Any]:
    _project_required()
    try:
        return ManagementCenter().project_action(
            project, body.profile or "default", body.action, body.value
        )
    except ValueError as exc:
        raise _bad_request(exc) from exc
    except Exception as exc:
        raise _server_error(exc) from exc
