from __future__ import annotations

import os
from pathlib import Path

try:
    from hermes_constants import get_hermes_home
except Exception:
    get_hermes_home = None


def _resolved_home() -> Path:
    explicit = str(os.environ.get("HERMES_HOME") or "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    if get_hermes_home is not None:
        try:
            return Path(get_hermes_home()).expanduser().resolve()
        except Exception:
            pass
    local = str(os.environ.get("LOCALAPPDATA") or "").strip()
    if local:
        candidate = Path(local) / "hermes"
        if candidate.exists():
            return candidate.resolve()
    return (Path.home() / ".hermes").resolve()


def current_agent() -> str:
    explicit = str(os.environ.get("HERMES_PROFILE") or os.environ.get("HERMES_PROFILE_NAME") or "").strip().lower()
    if explicit:
        return explicit
    home = _resolved_home()
    parts = [part.lower() for part in home.parts]
    if "profiles" in parts:
        index = len(parts) - 1 - parts[::-1].index("profiles")
        if index + 1 < len(home.parts):
            return str(home.parts[index + 1]).strip().lower() or "default"
    marker = root_hermes_home() / "active_profile"
    try:
        value = marker.read_text("utf-8").strip().lower()
        if value:
            return value
    except OSError:
        pass
    return "default"


def root_hermes_home() -> Path:
    home = _resolved_home()
    parts = [part.lower() for part in home.parts]
    if "profiles" in parts:
        index = len(parts) - 1 - parts[::-1].index("profiles")
        if index >= 1:
            return Path(*home.parts[:index]).resolve()
    return home
