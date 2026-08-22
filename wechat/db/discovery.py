from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from .base import BackendUnavailable


@dataclass(frozen=True)
class WeChatProcessInfo:
    hwnd: int
    pid: int
    executable: str
    version: str
    data_root: Path


def pid_from_hwnd(hwnd: int) -> int:
    if os.name != "nt":
        raise BackendUnavailable("Windows WeChat DB discovery requires Windows")
    import ctypes
    import ctypes.wintypes as wt
    pid = wt.DWORD()
    if not ctypes.windll.user32.GetWindowThreadProcessId(int(hwnd), ctypes.byref(pid)) or not pid.value:
        raise BackendUnavailable(f"Unable to resolve WeChat PID from HWND {hwnd}")
    return int(pid.value)


def _process(pid: int):
    try:
        import psutil
    except ImportError as exc:
        raise BackendUnavailable("psutil is required for automatic WeChat process discovery") from exc
    try:
        return psutil.Process(pid)
    except Exception as exc:
        raise BackendUnavailable(f"Unable to inspect WeChat process {pid}: {exc}") from exc


def _version_from_executable(path: str, cmdline: list[str]) -> str:
    for token in cmdline:
        match = re.search(r"(\d+\.\d+\.\d+\.\d+)", token)
        if match and ("Weixin" in token or "WeChat" in token):
            return match.group(1)
    parent = Path(path).parent
    for child in parent.iterdir() if parent.is_dir() else ():
        if child.is_dir() and re.fullmatch(r"\d+\.\d+\.\d+\.\d+", child.name):
            return child.name
    return "unknown"


def _data_root_from_cmdline(cmdline: list[str]) -> Path | None:
    for index, token in enumerate(cmdline):
        lower = token.lower()
        raw = None
        if lower.startswith("--wechat-files-path="):
            raw = token.split("=", 1)[1]
        elif lower == "--wechat-files-path" and index + 1 < len(cmdline):
            raw = cmdline[index + 1]
        if raw:
            candidate = Path(raw.strip().strip(chr(34))).expanduser()
            if candidate.is_dir():
                return candidate
    return None


def discover_process(hwnd: int) -> WeChatProcessInfo:
    pid = pid_from_hwnd(hwnd)
    proc = _process(pid)
    try:
        executable = proc.exe()
        cmdline = proc.cmdline()
    except Exception as exc:
        raise BackendUnavailable(f"Unable to inspect WeChat process metadata: {exc}") from exc
    data_root = _data_root_from_cmdline(cmdline)
    if data_root is None:
        candidates = [Path.home() / "Documents" / "xwechat_files", Path.home() / "Documents" / "WeChat Files"]
        data_root = next((path for path in candidates if path.is_dir()), None)
    if data_root is None:
        raise BackendUnavailable("No WeChat data root could be discovered automatically")
    return WeChatProcessInfo(int(hwnd), pid, executable, _version_from_executable(executable, cmdline), data_root)


def account_directories(data_root: Path) -> list[Path]:
    if not data_root.is_dir():
        return []
    return sorted([path for path in data_root.iterdir() if path.is_dir() and (path / "db_storage").is_dir()], key=lambda path: path.name.lower())
