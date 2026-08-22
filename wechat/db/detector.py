from __future__ import annotations

from typing import Any

from .base import BackendUnavailable, ReceiverBackend
from .discovery import discover_process


def detect_backend(resource: dict[str, Any]) -> ReceiverBackend:
    """Capability-probe the bound WeChat instance; version numbers are advisory only."""
    hwnd = int(resource.get("hwnd") or 0)
    if not hwnd:
        raise BackendUnavailable("Bound WeChat resource has no HWND")
    info = discover_process(hwnd)
    errors: list[str] = []
    try:
        from .backends.wechat4_sqlcipher import WeChat4SqlcipherBackend
        return WeChat4SqlcipherBackend(info)
    except Exception as exc:
        errors.append(f"encrypted-db: {exc}")
    raise BackendUnavailable("; ".join(errors) or f"No compatible DB receiver for WeChat {info.version}")
