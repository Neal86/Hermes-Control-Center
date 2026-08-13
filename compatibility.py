from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


class HermesCLI:
    """Small subprocess adapter used by Control Center management services.

    Hermes' official ``hermes_cli`` package does not export a HermesCLI class.
    Older Control Center modules imported that symbol from ``hermes_cli`` and
    therefore failed when installed inside the real Hermes dashboard process.
    """

    def __init__(self, hermes: str | None = None) -> None:
        self.hermes = hermes or shutil.which("hermes") or "hermes"

    def profile_command(self, profile: str | None, *args: str) -> list[str]:
        name = str(profile or "default").strip().lower()
        return [self.hermes, *(() if name == "default" else ("-p", name)), *args]

    @staticmethod
    def profile_env(home: Path) -> dict[str, str]:
        env = os.environ.copy()
        env["HERMES_HOME"] = str(home)
        return env

    def run_text(
        self,
        command: list[str],
        *,
        env: dict[str, str] | None = None,
        timeout: int = 60,
    ) -> str:
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
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
    """Expose the Control Center subprocess adapter on Hermes' package.

    Service modules historically use ``from hermes_cli import HermesCLI``.
    The official package intentionally does not define that symbol, so install
    it before any Management/Task service is imported.
    """
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
    requested = str(hermes or "hermes")
    resolved = shutil.which(requested)
    if resolved:
        return resolved
    candidate = Path(requested).expanduser()
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
            "Project tools require the Hermes/plugin process to be restarted after that upgrade."
        ),
    }
