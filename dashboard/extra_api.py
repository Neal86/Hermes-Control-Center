from __future__ import annotations

import ipaddress
import ctypes
import json
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

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
ProviderService = load_module("hcc_providers", "providers", "service").ProviderService
_bindings_module = load_module("hcc_resources", "resources", "bindings")
ResourceAccessError = _bindings_module.ResourceAccessError
ResourceBindings = _bindings_module.ResourceBindings
ResourceRegistry = load_module("hcc_resources", "resources", "registry").ResourceRegistry
BoundWeChatDesktop = load_module("hcc_resources", "resources", "wechat_bound").BoundWeChatDesktop

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
    provider: str = Field(min_length=1, max_length=128)
    profile: str = Field(default="default", min_length=1, max_length=64)


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
        if address.is_private or address.is_loopback or address.is_link_local or address.is_multicast or address.is_reserved or address.is_unspecified:
            raise ValueError("Model discovery cannot access private or local network addresses")
    return root


def _discover_models(base_url: str, credential: str | None) -> list[str]:
    root = _validate_public_https_url(base_url)
    endpoint = root if root.lower().endswith("/models") else root + "/models"
    headers = {"Accept": "application/json", "User-Agent": "Hermes-Control-Center/0.5.28"}
    if credential and str(credential).strip():
        headers["Authorization"] = "Bearer " + str(credential).strip()
    req = urllib.request.Request(endpoint, headers=headers, method="GET")
    opener = urllib.request.build_opener(urllib.request.HTTPHandler(), urllib.request.HTTPSHandler())
    try:
        with opener.open(req, timeout=20) as response:
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


def _provider_runtime_details(service: ProviderService, profile: str, provider: str) -> tuple[str, str | None]:
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


def _gateway_is_running(management: ManagementCenter, agent: str) -> bool:
    state = str(management.agent_get(agent).get("gateway") or "").strip().lower()
    return "running" in state and "not running" not in state and "stopped" not in state


def _configure_wechat_gateway(
    management: ManagementCenter,
    agent: str,
    resource_id: str,
    *,
    enabled: bool,
) -> dict[str, Any]:
    config_profile = "default" if management._gateway_multiplexes_profiles() else agent
    management._set_config(config_profile, "platforms.wechat_desktop.enabled", "true" if enabled else "false")
    if enabled:
        management._set_config(config_profile, "platforms.wechat_desktop.extra.bound_agent", agent)
        management._set_config(config_profile, "platforms.wechat_desktop.extra.bound_resource_id", resource_id)
    if not _gateway_is_running(management, agent):
        return {"ok": True, "skipped": True, "reason": "gateway_not_running"}
    restart = management.agent_action(agent, "gateway_restart")
    if not restart.get("ok"):
        raise RuntimeError(str(restart.get("warning") or "Gateway restart could not be verified"))
    return restart


@router.post("/resources/{resource_id}/bind")
def bind_resource(resource_id: str, body: BindingBody) -> dict[str, Any]:
    try:
        management = ManagementCenter()
        known = {str(row["name"]).strip().lower() for row in management.agent_list(probe_runtime=False)}
        agent = body.agent.strip().lower()
        if agent not in known:
            raise ValueError("unknown agent")
        bindings = ResourceBindings()
        previous_agent = bindings.list().get(resource_id)
        result = bindings.bind(resource_id, agent)
        resource = dict(result.get("resource") or {})
        if resource.get("kind") == "browser":
            port = int(resource.get("debug_port") or 0)
            if port <= 0:
                raise RuntimeError("Bound browser has no usable CDP port")
            cdp_url = f"http://127.0.0.1:{port}"
            # Hermes 0.20.5+ defaults to Browser Use CLI when browser.backend is unset.
            # A Control Center bound CDP browser must stay on the built-in browser_* stack,
            # otherwise tool availability is gated out before the CDP override is considered.
            management._set_config(agent, "browser.backend", "off")
            management._set_config(agent, "browser.cdp_url", cdp_url)
            restart = management.agent_action(agent, "gateway_restart")
            if not restart.get("ok"):
                raise RuntimeError(str(restart.get("warning") or "Gateway restart could not be verified"))
            result["gateway_restart"] = dict(restart, cdp_url=cdp_url)
        elif resource.get("kind") == "wechat":
            if previous_agent and previous_agent != agent and previous_agent in known:
                result["previous_gateway"] = _configure_wechat_gateway(
                    management,
                    previous_agent,
                    resource_id,
                    enabled=False,
                )
            result["gateway_restart"] = _configure_wechat_gateway(
                management,
                agent,
                resource_id,
                enabled=True,
            )
        return result
    except Exception as exc:
        raise _bad(exc) from exc


@router.delete("/resources/{resource_id}/bind")
def unbind_resource(resource_id: str) -> dict[str, Any]:
    try:
        return {"ok": True, "unbound": ResourceBindings().unbind(resource_id)}
    except Exception as exc:
        raise _bad(exc) from exc


def _activate_window(hwnd: int) -> bool:
    """Bring an exact top-level window forward across process input queues."""
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    root = int(user32.GetAncestor(hwnd, 2) or hwnd)  # GA_ROOT
    if not user32.IsWindow(root):
        return False
    foreground = int(user32.GetForegroundWindow() or 0)
    current_thread = int(kernel32.GetCurrentThreadId())
    target_thread = int(user32.GetWindowThreadProcessId(root, None) or 0)
    foreground_thread = int(user32.GetWindowThreadProcessId(foreground, None) or 0) if foreground else 0
    attached: list[tuple[int, int]] = []
    try:
        for left, right in ((current_thread, foreground_thread), (current_thread, target_thread)):
            if left and right and left != right and user32.AttachThreadInput(left, right, True):
                attached.append((left, right))
        if user32.IsIconic(root):
            user32.ShowWindow(root, 9)  # SW_RESTORE
        else:
            user32.ShowWindow(root, 5)  # SW_SHOW
        user32.SetWindowPos(root, 0, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)
        user32.BringWindowToTop(root)
        user32.SetForegroundWindow(root)
        user32.SetActiveWindow(root)
        user32.SetFocus(root)
    finally:
        for left, right in reversed(attached):
            user32.AttachThreadInput(left, right, False)
    return int(user32.GetForegroundWindow() or 0) == root


@router.post("/resources/{resource_id}/focus")
def focus_resource(resource_id: str) -> dict[str, Any]:
    try:
        if sys.platform != "win32":
            raise ValueError("window focus is supported on Windows only")
        resource = ResourceRegistry().get(resource_id, refresh=True)
        if not resource or not resource.get("online"):
            raise ValueError("resource is not online")
        hwnd = int(resource.get("hwnd") or 0)
        user32 = ctypes.windll.user32
        if not hwnd or not user32.IsWindow(hwnd):
            raise ValueError("resource window is no longer available")
        focused = _activate_window(hwnd)
        if not focused:
            raise RuntimeError("Windows refused to move the selected window to the foreground")
        return {"ok": True, "resource_id": resource_id, "hwnd": hwnd, "focused": focused}
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
        service = ProviderService()
        profile = str(body.profile or "default").strip().lower() or "default"
        provider = str(body.provider or "").strip().lower()
        base_url, credential = _provider_runtime_details(service, profile, provider)
        models = _discover_models(base_url, credential)
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
