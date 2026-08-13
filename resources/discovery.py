from __future__ import annotations

import hashlib
import json
import platform
import re
import subprocess
from ctypes import WINFUNCTYPE, WinError, byref, create_unicode_buffer, windll
from ctypes.wintypes import BOOL, DWORD, HWND, LPARAM
from typing import Any

_BROWSER_EXES = {"chrome.exe": "chrome", "msedge.exe": "edge"}
_WECHAT_EXES = {"wechat.exe", "weixin.exe", "wechatappex.exe"}
_PROFILE_RE = re.compile(r"--profile-directory(?:=|\s+)(?:\"([^\"]+)\"|'([^']+)'|([^\s]+))", re.I)
_USER_DATA_RE = re.compile(r"--user-data-dir(?:=|\s+)(?:\"([^\"]+)\"|'([^']+)'|([^\s]+))", re.I)
_REMOTE_PORT_RE = re.compile(r"--remote-debugging-port(?:=|\s+)(\d+)", re.I)


def _stable_id(kind: str, exe: str, *, user_data_dir: str = "", profile: str = "", instance: str = "") -> str:
    basis = "\0".join([kind, exe.lower(), user_data_dir.lower(), profile.lower(), instance.lower()])
    return f"{kind}:" + hashlib.sha256(basis.encode("utf-8", "replace")).hexdigest()[:20]


def _match(regex: re.Pattern[str], text: str) -> str:
    match = regex.search(text or "")
    if not match:
        return ""
    return next((value for value in match.groups() if value), "")


def _windows_by_pid() -> dict[int, list[dict[str, Any]]]:
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


def discover_resources() -> list[dict[str, Any]]:
    if platform.system() != "Windows":
        return []
    windows = _windows_by_pid()
    resources: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in _process_rows():
        name = str(row.get("Name") or "").lower()
        pid = int(row.get("ProcessId") or 0)
        exe_path = str(row.get("ExecutablePath") or "")
        command = str(row.get("CommandLine") or "")
        process_windows = windows.get(pid, [])
        if name in _WECHAT_EXES:
            if not process_windows:
                continue
            # Window titles change with the active chat and must never participate
            # in identity. One running WeChat process is one bindable resource.
            win = process_windows[0]
            resource_id = _stable_id("wechat", exe_path or name, instance=str(pid))
            if resource_id not in seen:
                seen.add(resource_id)
                resources.append({
                    "id": resource_id,
                    "kind": "wechat",
                    "app": "wechat",
                    "pid": pid,
                    "hwnd": win["hwnd"],
                    "title": win["title"],
                    "exe": exe_path or name,
                    "profile": "",
                    "user_data_dir": "",
                    "attachable": True,
                    "status": "ready",
                    "online": True,
                })
            continue

        browser = _BROWSER_EXES.get(name)
        if not browser or not process_windows:
            continue
        user_data = _match(_USER_DATA_RE, command)
        profile_name = _match(_PROFILE_RE, command) or "Default"
        port = _match(_REMOTE_PORT_RE, command)
        # Control Center currently attaches through BROWSER_CDP_URL, which needs
        # a TCP debugging port. remote-debugging-pipe alone is not usable here.
        attachable = bool(port)
        resource_id = _stable_id(
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
            "app": browser,
            "pid": pid,
            "hwnd": win["hwnd"],
            "title": win["title"],
            "exe": exe_path or name,
            "profile": profile_name,
            "user_data_dir": user_data,
            "debug_port": int(port) if port else None,
            "attachable": attachable,
            "status": "ready" if attachable else "not_attachable",
            "online": True,
        })
    return sorted(resources, key=lambda item: (item["kind"], item["app"], item["title"].lower(), item["pid"]))
