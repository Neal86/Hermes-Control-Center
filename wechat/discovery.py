from __future__ import annotations

import platform
import subprocess
from typing import Any

try:  # plugin package import
    from ..resources.discovery import _stable_id, windows_snapshot
except (ImportError, ValueError):  # source/platform import
    from resources.discovery import _stable_id, windows_snapshot

_WECHAT_EXES = {"wechat.exe", "weixin.exe", "wechatappex.exe"}


def wechat_conversation_title(hwnd: int) -> str:
    """Best-effort explicit UIA probe for callers that need the active chat title.

    Normal discovery deliberately does not call this because UI Automation can
    block for seconds per WeChat instance.
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
$candidates = $rows | Where-Object {
  $_.Y -ge ($rr.Y + 15) -and $_.Y -le ($rr.Y + 115) -and
  $_.X -ge ($rr.X + [Math]::Min(260, $rr.Width * 0.24)) -and
  $_.X -le ($rr.X + $rr.Width - 120) -and
  $_.W -ge 40 -and $_.H -le 70 -and
  $_.Name.Length -ge 2 -and $_.Name.Length -le 180 -and
  $_.Name -notmatch '^(微信|WeChat|搜索|Search|聊天|通讯录|收藏|朋友圈|小程序|视频号)$'
}
if (-not $candidates) { exit 0 }
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


def discover_wechat_resources(
    *,
    processes: list[dict[str, Any]] | None = None,
    windows: dict[int, list[dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    """Discover volatile WeChat runtime resources; logical identity lives elsewhere."""
    if processes is None or windows is None:
        processes, windows = windows_snapshot()
    resources: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in processes:
        name = str(row.get("Name") or "").lower()
        if name not in _WECHAT_EXES:
            continue
        pid = int(row.get("ProcessId") or 0)
        exe_path = str(row.get("ExecutablePath") or "")
        process_windows = windows.get(pid, [])
        if not process_windows:
            continue
        win = process_windows[0]
        resource_id = _stable_id("wechat", exe_path or name, instance=str(pid))
        if resource_id in seen:
            continue
        seen.add(resource_id)
        resources.append(
            {
                "id": resource_id,
                "kind": "wechat",
                "app": "wechat",
                "pid": pid,
                "hwnd": win["hwnd"],
                "title": win["title"],
                "conversation_title": "",
                "exe": exe_path or name,
                "profile": "",
                "user_data_dir": "",
                "attachable": True,
                "attach_reason": "uia_ready",
                "attach_error": "",
                "status": "ready",
                "online": True,
            }
        )
    return resources


def select_wechat_resources(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compatibility filter for callers that already have a mixed resource list."""
    return [dict(row) for row in rows if str(row.get("kind") or "").strip().lower() == "wechat"]
