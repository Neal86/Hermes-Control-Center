from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
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
    models: list[str] | None = Field(default=None, max_length=128)
    custom_name: str | None = Field(default=None, max_length=128)
    configured: bool | None = None
    oauth_status: str | None = Field(default=None, max_length=128)


class DiscoverModelsBody(StrictBody):
    base_url: str = Field(min_length=1, max_length=4096)
    api_key: str | None = Field(default=None, max_length=8192)


class WeChatBoundDryRunBody(StrictBody):
    agent: str = Field(min_length=1, max_length=64)
    resource_id: str | None = Field(default=None, max_length=128)
    chat: str = Field(min_length=1, max_length=256)
    text: str = Field(min_length=1, max_length=4000)


def _bad(exc: Exception) -> HTTPException:
    code = 409 if isinstance(exc, ResourceAccessError) else 400
    return HTTPException(status_code=code, detail=str(exc))


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


def _discover_models(base_url: str, api_key: str | None) -> list[str]:
    root = str(base_url or "").strip().rstrip("/")
    if not root.startswith(("http://", "https://")):
        raise ValueError("Base URL must start with http:// or https://")
    endpoint = root if root.lower().endswith("/models") else root + "/models"
    headers = {"Accept": "application/json", "User-Agent": "Hermes-Control-Center/0.5.13"}
    if api_key and str(api_key).strip():
        headers["Authorization"] = "Bearer " + str(api_key).strip()
    req = urllib.request.Request(endpoint, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            raw = response.read(4 * 1024 * 1024)
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read(4096).decode("utf-8", errors="replace")
        except Exception:
            pass
        raise ValueError(f"Provider model endpoint returned HTTP {exc.code}" + (f": {detail}" if detail else "")) from exc
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


def _read_saved_models(service: ProviderService, profile: str, provider: str, default_model: str = "") -> list[str]:
    meta = service._read_meta().get(profile, {})
    stored = meta.get(provider, {}) if isinstance(meta, dict) else {}
    models = _normalize_models(stored.get("models")) if isinstance(stored, dict) else []
    default_model = str(default_model or "").strip()
    if default_model and default_model not in models:
        models.insert(0, default_model)
    return models


def _save_models(service: ProviderService, profile: str, provider: str, models: list[str], runtime_provider_id: str, default_model: str) -> None:
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
        known = {str(row["name"]).strip().lower() for row in ManagementCenter().agent_list(probe_runtime=False)}
        agent = body.agent.strip().lower()
        if agent not in known:
            raise ValueError("unknown agent")
        return ResourceBindings().bind(resource_id, agent)
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
        port = resource.get("debug_port")
        if not port:
            raise ResourceAccessError("bound browser has no CDP endpoint")
        return {"resource": resource, "cdp_url": f"http://127.0.0.1:{int(port)}", "policy": "bound-only"}
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
    if body.agent.strip().lower() != agent.strip().lower():
        raise HTTPException(status_code=400, detail="agent mismatch")
    try:
        return BoundWeChatDesktop(agent, body.resource_id).send_message(body.chat, body.text, dry_run=True)
    except Exception as exc:
        raise _bad(exc) from exc


@router.get("/providers")
def providers(profile: str = "default") -> dict[str, Any]:
    try:
        service = ProviderService()
        items = service.list(profile)
        normalized = str(profile or "default").strip().lower() or "default"
        for row in items:
            row["models"] = _read_saved_models(service, normalized, str(row.get("id") or ""), str(row.get("default_model") or ""))
            row["supports_models"] = row.get("id") == "custom"
        return {"profile": profile, "items": items, "catalog": service.catalog()}
    except Exception as exc:
        raise _bad(exc) from exc


@router.post("/providers/discover-models")
def provider_discover_models(body: DiscoverModelsBody) -> dict[str, Any]:
    try:
        models = _discover_models(body.base_url, body.api_key)
        return {"items": models, "count": len(models)}
    except Exception as exc:
        raise _bad(exc) from exc


@router.put("/providers/{provider}")
def provider_save(provider: str, body: ProviderBody, profile: str = "default") -> dict[str, Any]:
    try:
        service = ProviderService()
        dumped = body.model_dump(exclude_none=True)
        models = _normalize_models(dumped.pop("models", [])) if "models" in dumped else None
        result = service.save(profile, provider, dumped)
        if models is not None:
            default_model = str(dumped.get("default_model") or "").strip()
            if models and not default_model:
                default_model = models[0]
                result = service.save(profile, provider, {"default_model": default_model})
            _save_models(
                service,
                str(profile or "default").strip().lower() or "default",
                provider,
                models,
                str(result.get("runtime_provider_id") or ""),
                default_model,
            )
            result["models"] = models
        return result
    except Exception as exc:
        raise _bad(exc) from exc
