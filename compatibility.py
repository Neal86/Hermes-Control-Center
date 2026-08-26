from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


def _resolve_hermes_command(hermes: str | None = None) -> str:
    requested = str(hermes or "").strip()
    if requested:
        resolved = shutil.which(requested)
        if resolved:
            return resolved
        candidate = Path(requested).expanduser()
        if candidate.is_file():
            return str(candidate.resolve())
        return requested

    resolved = shutil.which("hermes")
    if resolved:
        return resolved

    roots: list[Path] = []
    env_home = str(os.environ.get("HERMES_HOME") or "").strip()
    if env_home:
        roots.append(Path(env_home).expanduser())
    roots.append(Path.home() / ".hermes")

    executable_names = ("hermes.exe", "hermes") if os.name == "nt" else ("hermes", "hermes.exe")
    seen: set[str] = set()
    for root in roots:
        key = os.path.normcase(os.path.normpath(str(root)))
        if key in seen:
            continue
        seen.add(key)
        for executable_name in executable_names:
            candidate = root / "bin" / executable_name
            if candidate.is_file():
                return str(candidate.resolve())

    return "hermes"


class HermesCLI:
    """Small subprocess adapter used by Control Center management services.

    Hermes' official ``hermes_cli`` package does not export a HermesCLI class.
    Older Control Center modules imported that symbol from ``hermes_cli`` and
    therefore failed when installed inside the real Hermes dashboard process.
    """

    def __init__(self, hermes: str | None = None) -> None:
        self.hermes = _resolve_hermes_command(hermes)

    def profile_command(self, profile: str | None, *args: str) -> list[str]:
        name = str(profile or "default").strip().lower()
        return [self.hermes, *(() if name == "default" else ("-p", name)), *args]

    @staticmethod
    def profile_env(home: Path) -> dict[str, str]:
        env = os.environ.copy()
        env["HERMES_HOME"] = str(home)
        return env

    @staticmethod
    def _is_gateway_spawn_command(command: list[str]) -> bool:
        lowered = [str(part or "").strip().lower() for part in command]
        try:
            index = lowered.index("gateway")
        except ValueError:
            return False
        return index + 1 < len(lowered) and lowered[index + 1] in {"start", "restart"}

    def _launch_gateway_spawn_command(
        self,
        command: list[str],
        *,
        env: dict[str, str] | None = None,
    ) -> str:
        """Fire Windows gateway start/restart without waiting on the launcher.

        Hermes' Windows gateway start path can legitimately stay attached while it
        creates/repairs the persistent gateway process. Waiting for that CLI inside
        a Dashboard request made the UI sit on Working... and eventually time out.
        The management layer already verifies gateway state after this call, so the
        correct contract here is launch -> return -> poll status.
        """
        creationflags = 0
        for flag_name in ("CREATE_NO_WINDOW", "DETACHED_PROCESS", "CREATE_NEW_PROCESS_GROUP"):
            creationflags |= int(getattr(subprocess, flag_name, 0) or 0)
        subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
            close_fds=True,
            creationflags=creationflags,
        )
        return "gateway command launched in background"

    def run_text(
        self,
        command: list[str],
        *,
        env: dict[str, str] | None = None,
        timeout: int = 60,
    ) -> str:
        if os.name == "nt" and self._is_gateway_spawn_command(command):
            return self._launch_gateway_spawn_command(command, env=env)

        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
            check=False,
        )
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "Hermes command failed").strip()
            raise RuntimeError(f"{detail} (exit {proc.returncode})")
        return proc.stdout.strip()

    def run_json(
        self,
        command: list[str],
        *,
        env: dict[str, str] | None = None,
        timeout: int = 60,
    ) -> Any:
        text = self.run_text(command, env=env, timeout=timeout)
        if not text:
            return {}
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Hermes command did not return JSON: {text[:500]}") from exc


def install_hermes_cli_compat() -> None:
    """Expose the Control Center subprocess adapter on Hermes' package."""
    import hermes_cli as official_hermes_cli

    if getattr(official_hermes_cli, "HermesCLI", None) is None:
        setattr(official_hermes_cli, "HermesCLI", HermesCLI)


@dataclass(frozen=True)
class HermesCapabilities:
    hermes: bool
    plugins: bool
    dashboard: bool
    profile: bool
    project: bool
    cron: bool
    kanban: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_CACHE_TTL_SECONDS = 45.0
_cache_lock = threading.RLock()
_cache_value: HermesCapabilities | None = None
_cache_at = 0.0
_cache_binary = ""


def _supports(hermes: str, command: str) -> bool:
    try:
        proc = subprocess.run(
            [hermes, command, "--help"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    text = f"{proc.stdout}\n{proc.stderr}".lower()
    if "invalid choice" in text or "no such command" in text or "unknown command" in text:
        return False
    return proc.returncode == 0


def _resolve_binary(hermes: str | None = None) -> str | None:
    command = _resolve_hermes_command(hermes)
    resolved = shutil.which(command)
    if resolved:
        return resolved
    candidate = Path(command).expanduser()
    if candidate.is_file():
        return str(candidate.resolve())
    return None


def _detect_uncached(hermes: str | None = None) -> HermesCapabilities:
    binary = _resolve_binary(hermes)
    if not binary:
        return HermesCapabilities(False, False, False, False, False, False, False)
    return HermesCapabilities(
        hermes=True,
        plugins=_supports(binary, "plugins"),
        dashboard=_supports(binary, "dashboard"),
        profile=_supports(binary, "profile"),
        project=_supports(binary, "project"),
        cron=_supports(binary, "cron"),
        kanban=_supports(binary, "kanban"),
    )


def detect_capabilities(
    hermes: str | None = None,
    *,
    force: bool = False,
    ttl_seconds: float = _CACHE_TTL_SECONDS,
) -> HermesCapabilities:
    global _cache_at, _cache_binary, _cache_value
    binary = _resolve_binary(hermes) or ""
    now = time.monotonic()
    with _cache_lock:
        if (
            not force
            and _cache_value is not None
            and _cache_binary == binary
            and now - _cache_at < max(0.0, float(ttl_seconds))
        ):
            return _cache_value
        value = _detect_uncached(binary or None)
        _cache_value = value
        _cache_at = now
        _cache_binary = binary
        return value


def clear_capability_cache() -> None:
    global _cache_at, _cache_binary, _cache_value
    with _cache_lock:
        _cache_value = None
        _cache_at = 0.0
        _cache_binary = ""


def project_unavailable_payload() -> dict[str, Any]:
    return {
        "supported": False,
        "items": [],
        "message": (
            "This Hermes installation does not expose the native 'hermes project' command. "
            "Agents, Tasks and Dashboard remain available. Native Project support will "
            "appear after Hermes is upgraded and capabilities are refreshed; model-facing "
            "Project tools require the Hermes/plugin process to be restarted or reloaded "
            "after that upgrade."
        ),
    }
