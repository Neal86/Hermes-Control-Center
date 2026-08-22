from __future__ import annotations

import re
from typing import Any

try:  # plugin package import
    from ..resources.discovery import _stable_id, windows_snapshot
except (ImportError, ValueError):  # source/dashboard import
    from resources.discovery import _stable_id, windows_snapshot

from .runtime import probe_cdp

_BROWSER_EXES = {"chrome.exe": "chrome", "msedge.exe": "edge", "ixbrowser.exe": "ixbrowser"}
_PROFILE_RE = re.compile(r"--profile-directory(?:=|\s+)(?:\"([^\"]+)\"|'([^']+)'|([^\s]+))", re.I)
_USER_DATA_RE = re.compile(r"--user-data-dir(?:=|\s+)(?:\"([^\"]+)\"|'([^']+)'|([^\s]+))", re.I)
_REMOTE_PORT_RE = re.compile(r"--remote-debugging-port(?:=|\s+)(\d+)", re.I)


def _match(regex: re.Pattern[str], text: str) -> str:
    match = regex.search(text or "")
    if not match:
        return ""
    return next((value for value in match.groups() if value), "")


def discover_browser_resources(
    *,
    processes: list[dict[str, Any]] | None = None,
    windows: dict[int, list[dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    """Discover browser resources without owning WeChat/resource-registry logic."""
    if processes is None or windows is None:
        processes, windows = windows_snapshot()
    resources: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in processes:
        name = str(row.get("Name") or "").lower()
        browser = _BROWSER_EXES.get(name)
        if not browser:
            continue
        pid = int(row.get("ProcessId") or 0)
        exe_path = str(row.get("ExecutablePath") or "")
        command = str(row.get("CommandLine") or "")
        process_windows = windows.get(pid, [])
        if not process_windows:
            continue

        user_data = _match(_USER_DATA_RE, command)
        profile_name = _match(_PROFILE_RE, command) or "Default"
        port_text = _match(_REMOTE_PORT_RE, command)
        port = int(port_text) if port_text else None

        if port is None:
            attachable = False
            attach_reason = "remote_debugging_not_enabled"
            attach_error = "Browser was launched without a TCP remote-debugging port"
        else:
            attachable, probe_reason = probe_cdp(port)
            attach_reason = probe_reason
            attach_error = "" if attachable else "Remote-debugging port is present but the CDP endpoint is unreachable"

        # CDP controls a profile-wide browser instance; ordinary browser windows
        # remain individually addressable when no CDP endpoint exists.
        browser_windows = process_windows[:1] if attachable else process_windows
        for win in browser_windows:
            identity_instance = "" if attachable else str(win["hwnd"])
            resource_id = _stable_id(
                "browser",
                exe_path or name,
                user_data_dir=user_data,
                profile=profile_name,
                instance=identity_instance,
            )
            if resource_id in seen:
                continue
            seen.add(resource_id)
            resources.append(
                {
                    "id": resource_id,
                    "kind": "browser",
                    "app": browser,
                    "pid": pid,
                    "hwnd": win["hwnd"],
                    "title": win["title"],
                    "exe": exe_path or name,
                    "profile": profile_name,
                    "user_data_dir": user_data,
                    "debug_port": port,
                    "attachable": attachable,
                    "attach_reason": attach_reason,
                    "attach_error": attach_error,
                    "status": "ready" if attachable else "not_attachable",
                    "online": True,
                }
            )
    return resources


def select_browser_resources(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compatibility filter for callers that already have a mixed resource list."""
    return [dict(row) for row in rows if str(row.get("kind") or "").strip().lower() == "browser"]
