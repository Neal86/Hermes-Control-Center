from __future__ import annotations

import hashlib
import json
import platform
import subprocess
from ctypes import WINFUNCTYPE, WinError, byref, create_unicode_buffer, windll
from ctypes.wintypes import BOOL, DWORD, HWND, LPARAM
from typing import Any


def _stable_id(kind: str, exe: str, *, user_data_dir: str = "", profile: str = "", instance: str = "") -> str:
    basis = "\0".join([kind, exe.lower(), user_data_dir.lower(), profile.lower(), instance.lower()])
    return f"{kind}:" + hashlib.sha256(basis.encode("utf-8", "replace")).hexdigest()[:20]


def _windows_by_pid() -> dict[int, list[dict[str, Any]]]:
    """Shared Windows primitive: visible top-level windows grouped by process."""
    if platform.system() != "Windows":
        return {}
    user32 = windll.user32
    mapping: dict[int, list[dict[str, Any]]] = {}

    @WINFUNCTYPE(BOOL, HWND, LPARAM)
    def callback(hwnd: int, _: int) -> bool:
        try:
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buf = create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value.strip()
            if not title:
                return True
            pid = DWORD()
            user32.GetWindowThreadProcessId(hwnd, byref(pid))
            mapping.setdefault(int(pid.value), []).append({"hwnd": int(hwnd), "title": title})
        except Exception:
            pass
        return True

    if not user32.EnumWindows(callback, 0):
        raise WinError()
    return mapping


def _process_rows() -> list[dict[str, Any]]:
    """Shared Windows primitive: process metadata needed by resource domains."""
    if platform.system() != "Windows":
        return []
    script = (
        "$ErrorActionPreference='Stop';"
        "Get-CimInstance Win32_Process | "
        "Select-Object ProcessId,Name,ExecutablePath,CommandLine | ConvertTo-Json -Compress"
    )
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
            encoding="utf-8",
            errors="replace",
        )
        payload = json.loads(proc.stdout or "[]")
        if isinstance(payload, dict):
            payload = [payload]
        return payload if isinstance(payload, list) else []
    except Exception:
        return []


def windows_snapshot() -> tuple[list[dict[str, Any]], dict[int, list[dict[str, Any]]]]:
    """Run CIM + EnumWindows exactly once for all desktop resource domains."""
    if platform.system() != "Windows":
        return [], {}
    return _process_rows(), _windows_by_pid()


def _domain_discovery_functions():
    try:  # plugin package import
        from ..browser.discovery import discover_browser_resources
        from ..wechat.discovery import discover_wechat_resources
    except (ImportError, ValueError):  # source/dashboard import
        from browser.discovery import discover_browser_resources
        from wechat.discovery import discover_wechat_resources
    return discover_browser_resources, discover_wechat_resources


def discover_resources() -> list[dict[str, Any]]:
    """Compatibility/coordinator entry point; platform details live in domains."""
    processes, windows = windows_snapshot()
    if not processes and not windows:
        return []
    discover_browser_resources, discover_wechat_resources = _domain_discovery_functions()
    resources = [
        *discover_browser_resources(processes=processes, windows=windows),
        *discover_wechat_resources(processes=processes, windows=windows),
    ]
    return sorted(
        resources,
        key=lambda item: (
            str(item.get("kind") or ""),
            str(item.get("app") or ""),
            str(item.get("title") or "").lower(),
            int(item.get("pid") or 0),
        ),
    )


def _wechat_conversation_title(hwnd: int) -> str:
    """Backward-compatible alias for the WeChat-domain explicit title probe."""
    try:
        from ..wechat.discovery import wechat_conversation_title
    except (ImportError, ValueError):
        from wechat.discovery import wechat_conversation_title
    return wechat_conversation_title(hwnd)
