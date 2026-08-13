from __future__ import annotations

import os
from pathlib import Path


def current_agent() -> str:
    explicit = str(os.environ.get("HERMES_PROFILE") or os.environ.get("HERMES_PROFILE_NAME") or "").strip().lower()
    if explicit:
        return explicit
    home = Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes").expanduser()
    parts = [part.lower() for part in home.parts]
    if "profiles" in parts:
        index = len(parts) - 1 - parts[::-1].index("profiles")
        if index + 1 < len(home.parts):
            return str(home.parts[index + 1]).strip().lower() or "default"
    marker = home / "active_profile"
    try:
        value = marker.read_text("utf-8").strip().lower()
        if value:
            return value
    except OSError:
        pass
    return "default"


def root_hermes_home() -> Path:
    home = Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes").expanduser().resolve()
    parts = [part.lower() for part in home.parts]
    if "profiles" in parts:
        index = len(parts) - 1 - parts[::-1].index("profiles")
        if index >= 1:
            return Path(*home.parts[:index]).resolve()
    return home
