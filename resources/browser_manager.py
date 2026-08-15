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


def default_user_data_dir(browser: str = "chrome") -> Path:
    if platform.system() != "Windows":
        raise RuntimeError("browser profile import is currently supported on Windows only")
    local = Path(os.environ.get("LOCALAPPDATA") or "")
    if not str(local):
        raise RuntimeError("LOCALAPPDATA is unavailable")
    if str(browser or "chrome").strip().lower() == "edge":
        return (local / "Microsoft" / "Edge" / "User Data").resolve()
    return (local / "Google" / "Chrome" / "User Data").resolve()


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


def _stop_browser_process(pid: int, timeout: float = 10.0) -> None:
    pid = int(pid or 0)
    if pid <= 0:
        raise ValueError("browser pid is required")
    log_browser_event("existing_browser_stop_requested", pid=pid)
    subprocess.run(  # noqa: S603,S607 - Windows system utility, numeric PID only
        ["taskkill.exe", "/PID", str(pid), "/T"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    deadline = time.monotonic() + max(2.0, timeout)
    while time.monotonic() < deadline:
        probe = subprocess.run(  # noqa: S603,S607
            ["tasklist.exe", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if str(pid) not in (probe.stdout or ""):
            return
        time.sleep(0.25)
    subprocess.run(  # noqa: S603,S607
        ["taskkill.exe", "/F", "/PID", str(pid), "/T"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    time.sleep(0.5)


def _copy_profile_snapshot(source_root: Path, profile: str, target_root: Path) -> str:
    source_root = source_root.expanduser().resolve()
    profile = str(profile or "Default").strip() or "Default"
    source_profile = (source_root / profile).resolve()
    if not source_profile.is_dir():
        raise RuntimeError(f"browser profile directory was not found: {source_profile}")

    if target_root.exists() and any(target_root.iterdir()):
        backup = target_root.with_name(target_root.name + ".backup-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
        if backup.exists():
            shutil.rmtree(backup, ignore_errors=True)
        target_root.replace(backup)
    target_root.mkdir(parents=True, exist_ok=True)

    target_profile = target_root / "Default"
    shutil.copytree(source_profile, target_profile, dirs_exist_ok=True)
    for root_name in ("Local State", "First Run"):
        src = source_root / root_name
        if src.is_file():
            shutil.copy2(src, target_root / root_name)
    return str(target_profile)


def _reopen_original_browser(
    exe: Path,
    *,
    user_data_dir: Path,
    profile: str,
    browser: str,
    source_was_default: bool,
) -> None:
    args = [str(exe)]
    if not source_was_default:
        args.append(f"--user-data-dir={user_data_dir}")
    args.extend([f"--profile-directory={profile}", "--restore-last-session", "--no-first-run"])
    creationflags = 0
    for flag_name in ("CREATE_NEW_PROCESS_GROUP", "DETACHED_PROCESS"):
        creationflags |= int(getattr(subprocess, flag_name, 0))
    try:
        subprocess.Popen(  # noqa: S603
            args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=creationflags,
        )
        log_browser_event("existing_browser_reopened", browser=browser, profile=profile, user_data_dir=str(user_data_dir))
    except OSError as exc:
        log_browser_event("existing_browser_reopen_failed", browser=browser, profile=profile, error=str(exc))


def import_existing_browser_to_cdp(
    resource: dict[str, Any],
    agent: str,
    *,
    start_url: str = "https://wx.qq.com/",
) -> dict[str, Any]:
    """Clone a normal open Chrome/Edge profile into an Agent-owned CDP profile.

    Chrome does not allow retroactively enabling CDP on an already-running normal
    profile, and current Chrome versions ignore remote-debugging on the standard
    default data directory. This operation therefore closes the selected browser
    process, snapshots its profile into the Agent-managed data directory, reopens
    the user's original browser, then launches the imported snapshot with CDP.
    """
    if platform.system() != "Windows":
        raise RuntimeError("existing-browser CDP import is supported on Windows only")
    if str(resource.get("kind") or "") != "browser":
        raise ValueError("resource is not a browser")
    if not resource.get("online"):
        raise RuntimeError("browser resource is offline")
    if resource.get("attachable"):
        raise ValueError("browser already exposes a usable CDP endpoint")

    safe_agent = _safe_agent(agent)
    browser = "edge" if str(resource.get("app") or "").strip().lower() == "edge" else "chrome"
    exe_text = str(resource.get("exe") or "").strip()
    exe = Path(exe_text).expanduser().resolve() if exe_text else find_browser_executable(browser)
    if not exe.is_file():
        exe = find_browser_executable(browser)
    profile = str(resource.get("profile") or "Default").strip() or "Default"
    configured_root = str(resource.get("user_data_dir") or "").strip()
    default_root = default_user_data_dir(browser)
    source_root = Path(configured_root).expanduser().resolve() if configured_root else default_root
    source_was_default = source_root == default_root
    target_root = managed_profile_dir(safe_agent, browser)
    pid = int(resource.get("pid") or 0)

    log_browser_event(
        "existing_browser_import_started",
        agent=safe_agent,
        browser=browser,
        pid=pid,
        profile=profile,
        source_user_data_dir=str(source_root),
        target_user_data_dir=str(target_root),
    )

    _stop_browser_process(pid)
    try:
        imported_profile = _copy_profile_snapshot(source_root, profile, target_root)
    except Exception:
        _reopen_original_browser(
            exe,
            user_data_dir=source_root,
            profile=profile,
            browser=browser,
            source_was_default=source_was_default,
        )
        raise

    _reopen_original_browser(
        exe,
        user_data_dir=source_root,
        profile=profile,
        browser=browser,
        source_was_default=source_was_default,
    )
    launch = launch_managed_browser(
        safe_agent,
        browser=browser,
        start_url=start_url,
    )
    log_browser_event(
        "existing_browser_import_complete",
        agent=safe_agent,
        browser=browser,
        imported_profile=imported_profile,
        debug_port=launch.get("debug_port"),
    )
    return {
        "ok": True,
        "mode": "imported_existing_session",
        "source_resource_id": resource.get("id"),
        "source_profile": profile,
        "source_user_data_dir": str(source_root),
        "managed_profile": imported_profile,
        "launch": launch,
        "diagnostic_log": browser_diagnostic_log_path(),
    }


def browser_diagnostic_log_path() -> str:
    return str(_log_path())
