from __future__ import annotations

import ipaddress
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

from backend_packages_v2 import load_module

ProviderService = load_module("hcc_providers", "providers", "service").ProviderService

router = APIRouter()


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DiscoverModelsBody(StrictBody):
    provider: str = Field(min_length=1, max_length=128)
    profile: str = Field(default="default", min_length=1, max_length=64)


def _models_from_payload(payload: Any) -> list[str]:
    rows: Any = payload
    if isinstance(payload, dict):
        rows = payload.get("data")
        if not isinstance(rows, list):
            rows = payload.get("models")
    if not isinstance(rows, list):
        return []
    result: list[str] = []
    for row in rows:
        if isinstance(row, str):
            value = row
        elif isinstance(row, dict):
            value = row.get("id") or row.get("model") or row.get("name") or ""
        else:
            value = ""
        model = str(value or "").strip()
        if model and model not in result:
            result.append(model[:512])
    return sorted(result, key=str.lower)[:512]


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


def _runtime_details(service: Any, profile: str, provider: str) -> tuple[str, str]:
    rows = service.list(profile)
    row = next((item for item in rows if str(item.get("id")) == provider), None)
    if row is None:
        raise ValueError("unknown provider")
    base_url = str(row.get("base_url") or "").strip()
    if not base_url:
        raise ValueError("Provider Base URL is not configured")
    env_key = str(row.get("env_key") or "").strip()
    credential = ""
    if env_key:
        home = service._profile_home(profile, require_exists=True)
        credential = str(service._parse_env(home / ".env").get(env_key) or "").strip()
    if credential.lower().startswith("bearer "):
        credential = credential[7:].strip()
    return base_url, credential


def _request_models(endpoint: str, headers: dict[str, str]) -> tuple[int, bytes, str]:
    request = urllib.request.Request(endpoint, headers=headers, method="GET")
    opener = urllib.request.build_opener(urllib.request.HTTPHandler(), urllib.request.HTTPSHandler())
    try:
        with opener.open(request, timeout=20) as response:
            final_url = response.geturl()
            if urllib.parse.urlparse(final_url).hostname != urllib.parse.urlparse(endpoint).hostname:
                raise ValueError("Provider model endpoint redirected to a different hostname")
            return int(response.status), response.read(4 * 1024 * 1024), ""
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read(8192).decode("utf-8", errors="replace")
        except Exception:
            body = ""
        return int(exc.code), b"", body
    except urllib.error.URLError as exc:
        raise ValueError(f"Could not reach provider model endpoint: {exc.reason}") from exc


def _discover_models(base_url: str, credential: str) -> list[str]:
    root = _validate_public_https_url(base_url)
    endpoint = root if root.lower().endswith("/models") else root + "/models"
    common = {"Accept": "application/json", "User-Agent": "Hermes-Control-Center/0.5.30"}

    attempts: list[dict[str, str]] = []
    if credential:
        attempts.extend([
            {**common, "Authorization": "Bearer " + credential},
            {**common, "x-api-key": credential},
            {**common, "api-key": credential},
        ])
    else:
        attempts.append(common)

    last_status = 0
    last_body = ""
    for headers in attempts:
        status, raw, body = _request_models(endpoint, headers)
        last_status, last_body = status, body
        if 200 <= status < 300:
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError("Provider model endpoint did not return valid JSON") from exc
            models = _models_from_payload(payload)
            if not models:
                raise ValueError("Provider returned no model IDs")
            return models
        if status not in (401, 403):
            break

    detail = last_body.strip().replace("\r", " ").replace("\n", " ")
    if len(detail) > 1000:
        detail = detail[:1000] + "..."
    suffix = f": {detail}" if detail else ""
    raise ValueError(f"Provider model endpoint returned HTTP {last_status}{suffix}")


@router.post("/providers/discover-models")
def provider_discover_models(body: DiscoverModelsBody) -> dict[str, Any]:
    try:
        service = ProviderService()
        profile = str(body.profile or "default").strip().lower() or "default"
        provider = str(body.provider or "").strip().lower()
        base_url, credential = _runtime_details(service, profile, provider)
        models = _discover_models(base_url, credential)
        return {"items": models, "count": len(models)}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
