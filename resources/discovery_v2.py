from __future__ import annotations

from typing import Any

from . import discovery as legacy
from .browser_manager import probe_cdp


def _ixbrowser_resources() -> list[dict[str, Any]]:
    if legacy.platform.system() != "Windows":
        return []

    windows = legacy._windows_by_pid()
    resources: list[dict[str, Any]] = []
    seen: set[str] = set()

    for row in legacy._process_rows():
        name = str(row.get("Name") or "").lower()
        if name != "ixbrowser.exe":
            continue

        pid = int(row.get("ProcessId") or 0)
        process_windows = windows.get(pid, [])
        if not process_windows:
            continue

        exe_path = str(row.get("ExecutablePath") or "")
        command = str(row.get("CommandLine") or "")
        user_data = legacy._match(legacy._USER_DATA_RE, command)
        profile_name = legacy._match(legacy._PROFILE_RE, command) or "Default"
        port_text = legacy._match(legacy._REMOTE_PORT_RE, command)
        port = int(port_text) if port_text else None

        if port is None:
            attachable = False
            attach_reason = "remote_debugging_not_enabled"
            attach_error = "iXBrowser profile was launched without a TCP remote-debugging port"
        else:
            attachable, probe_reason = probe_cdp(port)
            attach_reason = probe_reason
            attach_error = "" if attachable else "Remote-debugging port is present but the CDP endpoint is unreachable"

        resource_id = legacy._stable_id(
            "browser",
            exe_path or name,
            user_data_dir=user_data,
            profile=profile_name,
        )
        if resource_id in seen:
            continue
        seen.add(resource_id)

        win = process_windows[0]
        resources.append({
            "id": resource_id,
            "kind": "browser",
            "app": "ixbrowser",
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
        })

    return resources


def discover_resources() -> list[dict[str, Any]]:
    rows = legacy.discover_resources()
    existing = {str(row.get("id")) for row in rows}
    for row in _ixbrowser_resources():
        if str(row.get("id")) not in existing:
            rows.append(row)
    return sorted(
        rows,
        key=lambda item: (
            str(item.get("kind")),
            str(item.get("app")),
            str(item.get("title", "")).lower(),
            int(item.get("pid") or 0),
        ),
    )
