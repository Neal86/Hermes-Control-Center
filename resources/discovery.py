from __future__ import annotations

import hashlib
import json
import platform
import re
import subprocess
from ctypes import WINFUNCTYPE, WinError, byref, create_unicode_buffer, windll
from ctypes.wintypes import BOOL, DWORD, HWND, LPARAM
from typing import Any

from .browser_manager import probe_cdp

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


def _wechat_conversation_title(hwnd: int) -> str:
    """Best-effort read of the active chat header using Windows UI Automation.

    WeChat's top-level Win32 window title is usually just "微信"/"WeChat". The
    useful identifier is the active conversation header inside the client. This
    routine only reads UI Automation metadata; it does not click or modify UI.
    """
    if platform.system() != "Windows" or not hwnd:
        return ""
    script = r"""
param([Int64]$Hwnd)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$root = [System.Windows.Automation.AutomationElement]::FromHandle([IntPtr]$Hwnd)
if ($null -eq $root) { exit 0 }
$rr = $root.Current.BoundingRectangle
$all = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
$rows = @()
foreach ($el in $all) {
  try {
    $name = [string]$el.Current.Name
    if ([string]::IsNullOrWhiteSpace($name)) { continue }
    $br = $el.Current.BoundingRectangle
    if ($br.Width -le 0 -or $br.Height -le 0) { continue }
    $ct = $el.Current.ControlType.ProgrammaticName
    $rows += [pscustomobject]@{ Name=$name.Trim(); X=$br.X; Y=$br.Y; W=$br.Width; H=$br.Height; Type=$ct }
  } catch {}
}
# The active conversation header is normally in the upper center/right content
# pane. Restrict candidates to that band so chat messages/sidebar names do not
# get mistaken for the header.
$candidates = $rows | Where-Object {
  $_.Y -ge ($rr.Y + 15) -and $_.Y -le ($rr.Y + 115) -and
  $_.X -ge ($rr.X + [Math]::Min(260, $rr.Width * 0.24)) -and
  $_.X -le ($rr.X + $rr.Width - 120) -and
  $_.W -ge 40 -and $_.H -le 70 -and
  $_.Name.Length -ge 2 -and $_.Name.Length -le 180 -and
  $_.Name -notmatch '^(微信|WeChat|搜索|Search|聊天|通讯录|收藏|朋友圈|小程序|视频号)$'
}
if (-not $candidates) { exit 0 }
# Prefer text-like controls near the top and toward the center of the content pane.
$best = $candidates | Sort-Object `
  @{Expression={ if ($_.Type -match 'Text|Button') {0} else {1} }}, `
  @{Expression={ [Math]::Abs($_.Y - ($rr.Y + 55)) }}, `
  @{Expression={ [Math]::Abs(($_.X + $_.W/2) - ($rr.X + $rr.Width*0.62)) }} | Select-Object -First 1
if ($best) { [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false); Write-Output $best.Name }
"""
    try:
        proc = subprocess.run(
            [
                "powershell.exe",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                script,
                "-Hwnd",
                str(int(hwnd)),
            ],
            capture_output=True,
            text=True,
            timeout=6,
            check=True,
            encoding="utf-8",
            errors="replace",
        )
        title = (proc.stdout or "").strip().splitlines()
        value = title[-1].strip() if title else ""
        if value.lower() in {"wechat", "微信", "weixin"}:
            return ""
        return value[:180]
    except Exception:
        return ""


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
                conversation_title = _wechat_conversation_title(int(win["hwnd"]))
                resources.append({
                    "id": resource_id,
                    "kind": "wechat",
                    "app": "wechat",
                    "pid": pid,
                    "hwnd": win["hwnd"],
                    "title": win["title"],
                    "conversation_title": conversation_title,
                    "exe": exe_path or name,
                    "profile": "",
                    "user_data_dir": "",
                    "attachable": True,
                    "attach_reason": "uia_ready",
                    "attach_error": "",
                    "status": "ready",
                    "online": True,
                })
            continue

        browser = _BROWSER_EXES.get(name)
        if not browser or not process_windows:
            continue
        user_data = _match(_USER_DATA_RE, command)
        profile_name = _match(_PROFILE_RE, command) or "Default"
        port_text = _match(_REMOTE_PORT_RE, command)
        port = int(port_text) if port_text else None

        # A command-line switch alone is not enough. Modern Chrome can ignore
        # remote-debugging switches for the normal default data directory. We
        # therefore probe /json/version and only call a browser attachable when
        # the loopback DevTools endpoint actually answers with a websocket URL.
        if port is None:
            attachable = False
            attach_reason = "remote_debugging_not_enabled"
            attach_error = "Browser was launched without a TCP remote-debugging port"
        else:
            attachable, probe_reason = probe_cdp(port)
            attach_reason = probe_reason
            attach_error = "" if attachable else "Remote-debugging port is present but the CDP endpoint is unreachable"

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
            "debug_port": port,
            "attachable": attachable,
            "attach_reason": attach_reason,
            "attach_error": attach_error,
            "status": "ready" if attachable else "not_attachable",
            "online": True,
        })
    return sorted(resources, key=lambda item: (item["kind"], item["app"], item["title"].lower(), item["pid"]))
