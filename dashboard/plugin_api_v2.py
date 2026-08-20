from __future__ import annotations

import importlib.util
import ipaddress
import json
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

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


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProviderBody(StrictBody):
    api_key: str | None = Field(default=None, max_length=8192)
    clear_api_key: bool = False
    base_url: str | None = Field(default=None, max_length=4096)
    default_model: str | None = Field(default=None, max_length=512)
    models: list[str] | None = Field(default=None, max_length=128)
    custom_name: str | None = Field(default=None, max_length=128)
    configured: bool | None = None
    oauth_status: str | None = Field(default=None, max_length=128)


class DiscoverModelsBody(StrictBody):
    provider: str = Field(min_length=1, max_length=128)
    profile: str = Field(default="default", min_length=1, max_length=64)


def _server_error(exc: Exception) -> HTTPException:
    return HTTPException(status_code=500, detail=str(exc))


def _bad_request(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


def _normalize_models(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        model = str(item or "").strip()
        if model and model not in result:
            result.append(model[:512])
        if len(result) >= 128:
            break
    return result


def _models_from_payload(payload: Any) -> list[str]:
    rows: Any = payload
    if isinstance(payload, dict):
        rows = payload.get("data")
        if not isinstance(rows, list):
            rows = payload.get("models")
    if not isinstance(rows, list):
        return []
    models: list[str] = []
    for row in rows:
        if isinstance(row, str):
            value = row
        elif isinstance(row, dict):
            value = row.get("id") or row.get("model") or row.get("name") or ""
        else:
            value = ""
        model = str(value or "").strip()
        if model and model not in models:
            models.append(model[:512])
    return sorted(models, key=str.lower)[:512]


def _validate_public_https_url(base_url: str) -> str:
    root = str(base_url or "").strip().rstrip("/")
    parsed = urllib.parse.urlparse(root)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Model discovery requires a public HTTPS Base URL")
    try:
        infos = socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ValueError(f"Could not resolve provider hostname: {exc}") from exc
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
            or address.is_unspecified
        ):
            raise ValueError("Model discovery cannot access private or local network addresses")
    return root


def _discover_models(base_url: str, credential: str | None) -> list[str]:
    root = _validate_public_https_url(base_url)
    endpoint = root if root.lower().endswith("/models") else root + "/models"
    headers = {"Accept": "application/json", "User-Agent": "Hermes-Control-Center/0.5.27"}
    if credential and str(credential).strip():
        headers["Authorization"] = "Bearer " + str(credential).strip()
    request = urllib.request.Request(endpoint, headers=headers, method="GET")
    opener = urllib.request.build_opener(urllib.request.HTTPHandler(), urllib.request.HTTPSHandler())
    try:
        with opener.open(request, timeout=20) as response:
            final_url = response.geturl()
            if urllib.parse.urlparse(final_url).hostname != urllib.parse.urlparse(endpoint).hostname:
                raise ValueError("Provider model endpoint redirected to a different hostname")
            raw = response.read(4 * 1024 * 1024)
    except urllib.error.HTTPError as exc:
        raise ValueError(f"Provider model endpoint returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise ValueError(f"Could not reach provider model endpoint: {exc.reason}") from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Provider model endpoint did not return valid JSON") from exc
    models = _models_from_payload(payload)
    if not models:
        raise ValueError("Provider returned no model IDs")
    return models


def _read_saved_models(service: Any, profile: str, provider: str, default_model: str = "") -> list[str]:
    meta = service._read_meta().get(profile, {})
    stored = meta.get(provider, {}) if isinstance(meta, dict) else {}
    models = _normalize_models(stored.get("models")) if isinstance(stored, dict) else []
    default_model = str(default_model or "").strip()
    if default_model and default_model not in models:
        models.insert(0, default_model)
    return models


def _save_models(
    service: Any,
    profile: str,
    provider: str,
    models: list[str],
    runtime_provider_id: str,
    default_model: str,
) -> None:
    payload = service._read_meta()
    by_profile = payload.setdefault(profile, {})
    if not isinstance(by_profile, dict):
        by_profile = {}
        payload[profile] = by_profile
    current = by_profile.setdefault(provider, {})
    if not isinstance(current, dict):
        current = {}
        by_profile[provider] = current
    current["models"] = models
    service._write_meta(payload)

    if provider != "custom" or not runtime_provider_id:
        return
    config = service._read_config(profile)
    providers = config.get("providers")
    if not isinstance(providers, dict):
        providers = {}
        config["providers"] = providers
    entry = providers.get(runtime_provider_id)
    if not isinstance(entry, dict):
        return
    if models:
        entry["models"] = models
    else:
        entry.pop("models", None)
    if default_model:
        entry["default_model"] = default_model
    else:
        entry.pop("default_model", None)
    providers[runtime_provider_id] = entry
    service._write_config(profile, config)


def _provider_runtime_details(service: Any, profile: str, provider: str) -> tuple[str, str | None]:
    rows = service.list(profile)
    row = next((item for item in rows if str(item.get("id")) == provider), None)
    if row is None:
        raise ValueError("unknown provider")
    base_url = str(row.get("base_url") or "").strip()
    if not base_url:
        raise ValueError("Provider Base URL is not configured")
    env_key = str(row.get("env_key") or "").strip()
    credential = None
    if env_key:
        home = service._profile_home(profile, require_exists=True)
        credential = service._parse_env(home / ".env").get(env_key)
    return base_url, credential


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
def upcoming(
    hours: int = Query(168, ge=1, le=2160),
    profile: str | None = None,
    limit: int = Query(300, ge=1, le=1000),
) -> dict[str, Any]:
    try:
        rows = TaskCenter().upcoming(hours=hours, profile=profile, limit=limit)
        return {"items": rows}
    except Exception as exc:
        raise _server_error(exc) from exc


@router.get("/providers")
def providers(profile: str = "default") -> dict[str, Any]:
    try:
        service = ProviderService()
        normalized = str(profile or "default").strip().lower() or "default"
        items = service.list(normalized)
        for row in items:
            provider_id = str(row.get("id") or "")
            row["models"] = _read_saved_models(
                service,
                normalized,
                provider_id,
                str(row.get("default_model") or ""),
            )
            row["supports_models"] = provider_id == "custom"
        return {"profile": normalized, "items": items, "catalog": service.catalog()}
    except Exception as exc:
        raise _server_error(exc) from exc


@router.post("/providers/discover-models")
def provider_discover_models(body: DiscoverModelsBody) -> dict[str, Any]:
    try:
        service = ProviderService()
        profile = str(body.profile or "default").strip().lower() or "default"
        provider = str(body.provider or "").strip().lower()
        base_url, credential = _provider_runtime_details(service, profile, provider)
        models = _discover_models(base_url, credential)
        return {"items": models, "count": len(models)}
    except Exception as exc:
        raise _bad_request(exc) from exc


@router.put("/providers/{provider}")
def provider_save(provider: str, body: ProviderBody, profile: str = "default") -> dict[str, Any]:
    try:
        service = ProviderService()
        normalized = str(profile or "default").strip().lower() or "default"
        provider_id = str(provider or "").strip().lower()
        dumped = body.model_dump(exclude_none=True)
        models = _normalize_models(dumped.pop("models", [])) if "models" in dumped else None
        result = service.save(normalized, provider_id, dumped)
        if models is not None:
            default_model = str(dumped.get("default_model") or "").strip()
            if models and not default_model:
                default_model = models[0]
                result = service.save(normalized, provider_id, {"default_model": default_model})
            _save_models(
                service,
                normalized,
                provider_id,
                models,
                str(result.get("runtime_provider_id") or ""),
                default_model,
            )
            result["models"] = models
        return result
    except Exception as exc:
        raise _bad_request(exc) from exc


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
