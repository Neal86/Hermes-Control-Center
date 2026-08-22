from __future__ import annotations

import hashlib
from typing import Any


def normalize_agent(agent: str) -> str:
    value = str(agent or "").strip().lower()
    if not value:
        raise ValueError("agent is required")
    return value


def stable_binding_id(agent: str) -> str:
    """Stable logical WeChat binding id independent of PID/HWND."""
    normalized = normalize_agent(agent)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:20]
    return f"wechat-binding:{digest}"


def resource_hints(resource: dict[str, Any]) -> dict[str, str]:
    """Persist only restart-stable, non-secret hints used for safe recovery."""
    return {
        "app": str(resource.get("app") or "wechat").strip().lower(),
        "exe": str(resource.get("exe") or "").strip().lower(),
        "title": str(resource.get("title") or "").strip().lower(),
    }


def compatible_resource(record: dict[str, Any], resource: dict[str, Any]) -> bool:
    if str(resource.get("kind") or "").strip().lower() != "wechat":
        return False
    hints = record.get("hints") if isinstance(record, dict) else None
    hints = hints if isinstance(hints, dict) else {}
    wanted_app = str(hints.get("app") or "wechat").strip().lower()
    actual_app = str(resource.get("app") or "wechat").strip().lower()
    if wanted_app and actual_app and wanted_app != actual_app:
        return False
    wanted_exe = str(hints.get("exe") or "").strip().lower()
    actual_exe = str(resource.get("exe") or "").strip().lower()
    if wanted_exe and actual_exe and wanted_exe != actual_exe:
        return False
    # Window titles are only used as an additional discriminator when both sides
    # expose one. Never use PID/HWND as stable identity.
    wanted_title = str(hints.get("title") or "").strip().lower()
    actual_title = str(resource.get("title") or "").strip().lower()
    if wanted_title and actual_title and wanted_title != actual_title:
        return False
    return True
