from __future__ import annotations

import json
import os
import platform
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .context import root_hermes_home


def _data_root() -> Path:
    root = root_hermes_home() / "plugin-data" / "hermes-extensions"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _log_path() -> Path:
    path = _data_root() / "resources" / "browser-attach.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def log_browser_event(event: str, **fields: Any) -> None:
    """Append a small diagnostic record without page content, cookies, or credentials."""
    payload = {
        "ts": datetime.now(UTC).isoformat(),
        "event": str(event or "unknown"),
    }
    payload.update({key: value for key, value in fields.items() if value not in (None, "")})
    try:
        with _log_path().open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    except OSError:
        pass


def probe_cdp(port: int, timeout: float = 0.8) -> tuple[bool, str]:
    """Verify that a loopback Chrome DevTools HTTP endpoint is actually reachable."""
    try:
        port = int(port)
    except (TypeError, ValueError):
        return False, "invalid_debug_port"
    if port <= 0 or port > 65535:
        return False, "invalid_debug_port"
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/json/version",
        headers={"Accept": "application/json", "User-Agent": "Hermes-Control-Center/BrowserProbe"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=max(0.1, float(timeout))) as response:  # noqa: S310 - loopback only
            payload = json.loads(response.read(1024 * 1024).decode("utf-8", "replace"))
        if not isinstance(payload, dict):
            return False, "cdp_invalid_response"
        if not str(payload.get("webSocketDebuggerUrl") or "").strip():
            return False, "cdp_missing_websocket"
        return True, "cdp_ready"
    except urllib.error.HTTPError as exc:
        return False, f"cdp_http_{exc.code}"
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        return False, f"cdp_unreachable:{type(exc).__name__}"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _browser_candidates(browser: str) -> list[Path]:
    browser = str(browser or "chrome").strip().lower()
    local = Path(os.environ.get("LOCALAPPDATA") or "")
    program_files = Path(os.environ.get("PROGRAMFILES") or "")
    program_files_x86 = Path(os.environ.get("PROGRAMFILES(X86)") or "")
    if browser == "edge":
        names = [
            program_files_x86 / "Microsoft" / "Edge" / "Application" / "msedge.exe",
            program_files / "Microsoft" / "Edge" / "Application" / "msedge.exe",
            local / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        ]
        which = shutil.which("msedge.exe") or shutil.which("msedge")
    else:
        names = [
            program_files / "Google" / "Chrome" / "Application" / "chrome.exe",
            program_files_x86 / "Google" / "Chrome" / "Application" / "chrome.exe",
            local / "Google" / "Chrome" / "Application" / "chrome.exe",
        ]
        which = shutil.which("chrome.exe") or shutil.which("chrome")
    if which:
        names.insert(0, Path(which))
    return [path for path in names if str(path) and path.is_file()]


def find_browser_executable(browser: str = "chrome") -> Path:
    if platform.system() != "Windows":
        raise RuntimeError("managed browser launch is currently supported on Windows only")
    candidates = _browser_candidates(browser)
    if not candidates:
        raise RuntimeError(f"{browser or 'chrome'} executable was not found")
    return candidates[0].resolve()


def _safe_agent(agent: str) -> str:
    value = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "-" for ch in str(agent or "").strip().lower())
    value = value.strip("-._")[:64]
    if not value:
        raise ValueError("agent is required")
    return value


def managed_profile_dir(agent: str, browser: str = "chrome") -> Path:
    safe_agent = _safe_agent(agent)
    safe_browser = "edge" if str(browser).strip().lower() == "edge" else "chrome"
    path = _data_root() / "browser-profiles" / safe_agent / safe_browser
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def launch_managed_browser(
    agent: str,
    *,
    browser: str = "chrome",
    start_url: str = "https://wx.qq.com/",
    timeout: float = 12.0,
) -> dict[str, Any]:
    """Launch an Agent-owned Chromium browser with a dedicated profile and loopback CDP."""
    safe_agent = _safe_agent(agent)
    browser = "edge" if str(browser).strip().lower() == "edge" else "chrome"
    exe = find_browser_executable(browser)
    profile_dir = managed_profile_dir(safe_agent, browser)
    start_url = str(start_url or "https://wx.qq.com/").strip() or "https://wx.qq.com/"
    if not (start_url.startswith("https://") or start_url.startswith("http://")):
        raise ValueError("start_url must use http or https")

    last_error = ""
    for attempt in range(1, 4):
        port = _free_port()
        args = [
            str(exe),
            f"--remote-debugging-port={port}",
            "--remote-debugging-address=127.0.0.1",
            f"--user-data-dir={profile_dir}",
            "--profile-directory=Default",
            "--no-first-run",
            "--no-default-browser-check",
            start_url,
        ]
        creationflags = 0
        for flag_name in ("CREATE_NEW_PROCESS_GROUP", "DETACHED_PROCESS"):
            creationflags |= int(getattr(subprocess, flag_name, 0))
        try:
            process = subprocess.Popen(  # noqa: S603 - executable resolved from trusted installation paths
                args,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                creationflags=creationflags,
            )
        except OSError as exc:
            last_error = f"launch_failed:{type(exc).__name__}:{exc}"
            log_browser_event(
                "launch_failed",
                agent=safe_agent,
                browser=browser,
                executable=str(exe),
                attempt=attempt,
                error=last_error,
            )
            continue

        log_browser_event(
            "launch_started",
            agent=safe_agent,
            browser=browser,
            pid=process.pid,
            debug_port=port,
            user_data_dir=str(profile_dir),
            attempt=attempt,
        )
        deadline = time.monotonic() + max(2.0, float(timeout))
        while time.monotonic() < deadline:
            if process.poll() is not None:
                last_error = f"browser_exited:{process.returncode}"
                break
            ready, reason = probe_cdp(port, timeout=0.5)
            if ready:
                log_browser_event(
                    "cdp_ready",
                    agent=safe_agent,
                    browser=browser,
                    pid=process.pid,
                    debug_port=port,
                    user_data_dir=str(profile_dir),
                )
                return {
                    "ok": True,
                    "agent": safe_agent,
                    "browser": browser,
                    "pid": int(process.pid),
                    "debug_port": port,
                    "cdp_url": f"http://127.0.0.1:{port}",
                    "user_data_dir": str(profile_dir),
                    "start_url": start_url,
                    "attach_reason": reason,
                }
            last_error = reason
            time.sleep(0.2)

        log_browser_event(
            "cdp_failed",
            agent=safe_agent,
            browser=browser,
            pid=process.pid,
            debug_port=port,
            user_data_dir=str(profile_dir),
            attempt=attempt,
            error=last_error,
        )
        if process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass
        time.sleep(0.2)

    raise RuntimeError(f"managed browser could not expose CDP: {last_error or 'unknown error'}")


def browser_diagnostic_log_path() -> str:
    return str(_log_path())
