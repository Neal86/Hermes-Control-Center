from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query

DASHBOARD_ROOT = Path(__file__).resolve().parent
PLUGIN_ROOT = DASHBOARD_ROOT.parent
if str(DASHBOARD_ROOT) not in sys.path:
    sys.path.insert(0, str(DASHBOARD_ROOT))

from backend_packages_v2 import load_module


def _load_file(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


compat = _load_file(PLUGIN_ROOT / "compatibility.py", "hcc_compatibility")
compat.install_hermes_cli_compat()
TaskCenter = load_module("hcc_task_center", "task_center", "service_v3").TaskCenter
ManagementCenter = load_module("hcc_management", "management", "routed_service").ManagementCenter
ProviderService = load_module("hcc_providers", "providers", "service").ProviderService
ResourceBindings = load_module("hcc_resources", "resources", "bindings").ResourceBindings
ResourceRegistry = load_module("hcc_resources", "resources", "registry").ResourceRegistry
OverviewModule = load_module("hcc_management", "management", "overview")

router = APIRouter()


def _server_error(exc: Exception) -> HTTPException:
    return HTTPException(status_code=500, detail=str(exc))


@router.get("/capabilities")
def capabilities(refresh: bool = False) -> dict[str, Any]:
    caps = compat.detect_capabilities(force=refresh)
    return {"capabilities": caps.to_dict(), "project_supported": caps.project, "backend": "isolated-v2"}


@router.get("/management/overview")
def management_overview() -> dict[str, Any]:
    try:
        caps = compat.detect_capabilities()
        return OverviewModule.build_management_overview(
            caps=caps,
            manager=ManagementCenter(),
            task_center=TaskCenter(),
            project_unavailable_message=str(compat.project_unavailable_payload().get("message") or "Projects unavailable"),
        )
    except Exception as exc:
        raise _server_error(exc) from exc


@router.get("/agents")
def agents() -> dict[str, Any]:
    try:
        return {"items": ManagementCenter().agent_list()}
    except Exception as exc:
        raise _server_error(exc) from exc


@router.get("/overview")
def task_overview(profile: str | None = None, include_completed: bool = False) -> dict[str, Any]:
    try:
        return TaskCenter().overview(profile=profile, include_completed=include_completed)
    except Exception as exc:
        raise _server_error(exc) from exc


@router.get("/upcoming")
def upcoming(hours: int = Query(168, ge=1, le=2160), profile: str | None = None, limit: int = Query(300, ge=1, le=1000)) -> dict[str, Any]:
    try:
        center = TaskCenter()
        try:
            rows = center.upcoming(hours=hours, profile=profile, limit=limit)
        except TypeError:
            rows = center.upcoming(hours=hours, profile=profile)[:limit]
        return {"items": rows}
    except Exception as exc:
        raise _server_error(exc) from exc


@router.get("/providers")
def providers(profile: str = "default") -> dict[str, Any]:
    try:
        service = ProviderService()
        return {"profile": profile, "items": service.list(profile), "catalog": service.catalog()}
    except Exception as exc:
        raise _server_error(exc) from exc


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
        raise _server_error(exc) from exc


@router.get("/wechat/health")
def wechat_health() -> dict[str, Any]:
    return {"status": "available", "backend": "isolated-v2"}
