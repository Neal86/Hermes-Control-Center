from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

try:
    import yaml
except Exception:  # pragma: no cover
    yaml = None

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))
from compatibility import HermesCLI  # noqa: E402

_PROFILE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def _safe_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    if yaml is None:
        raise RuntimeError("PyYAML is required for Hermes management")
    try:
        value = yaml.safe_load(path.read_text("utf-8"))
    except (OSError, ValueError, yaml.YAMLError):
        return {}
    return value if isinstance(value, dict) else {}


def _nested(data: dict[str, Any], *keys: str) -> Any:
    cur: Any = data
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _path_key(value: str | Path | None) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    path = Path(text).expanduser()
    try:
        path = path.resolve(strict=False)
    except (OSError, ValueError):
        path = Path(os.path.abspath(os.path.normpath(str(path))))
    return os.path.normcase(os.path.normpath(str(path)))


class ManagementCenter:
    """Management layer over native Hermes Profiles and Projects."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")).expanduser().resolve()
        self.cli = HermesCLI()
        self.hermes = self.cli.hermes

    @staticmethod
    def _normalize_profile(name: str | None) -> str:
        value = str(name or "default").strip().lower()
        if value == "default":
            return value
        if not _PROFILE_RE.fullmatch(value):
            raise ValueError("invalid profile name")
        return value

    def _profile_home(self, name: str | None) -> Path:
        profile = self._normalize_profile(name)
        if profile == "default":
            return self.root
        profiles_root = (self.root / "profiles").resolve()
        home = (profiles_root / profile).resolve()
        if profiles_root != home and profiles_root not in home.parents:
            raise ValueError("invalid profile path")
        return home

    def profile_list(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for name in ["default", *self._profile_dirs()]:
            home = self._profile_home(name)
            cfg = _safe_yaml(home / "config.yaml")
            items.append({"name": name, "home": str(home), "model": _nested(cfg, "model") or _nested(cfg, "llm", "model")})
        return items

    def _profile_dirs(self) -> list[str]:
        root = self.root / "profiles"
        if not root.exists():
            return []
        return sorted(p.name for p in root.iterdir() if p.is_dir() and _PROFILE_RE.fullmatch(p.name))

    def _json_command(self, profile: str | None, *args: str, timeout: int = 60) -> Any:
        home = self._profile_home(profile)
        command = self.cli.profile_command(profile, *args)
        return self.cli.run_json(command, env=self.cli.profile_env(home), timeout=timeout)

    def _text_command(self, profile: str | None, *args: str, timeout: int = 60) -> str:
        home = self._profile_home(profile)
        command = self.cli.profile_command(profile, *args)
        return self.cli.run_text(command, env=self.cli.profile_env(home), timeout=timeout)

    @staticmethod
    def _items(value: Any) -> list[dict[str, Any]]:
        if isinstance(value, list):
            return [x if isinstance(x, dict) else {"value": x} for x in value]
        if isinstance(value, dict):
            for key in ("items", "agents", "projects", "profiles"):
                if isinstance(value.get(key), list):
                    return [x if isinstance(x, dict) else {"value": x} for x in value[key]]
            return [value]
        return []

    def agent_list(self, profile: str | None = None, probe_runtime: bool = True) -> list[dict[str, Any]]:
        if probe_runtime:
            for argv in (("agent", "list", "--json"), ("agents", "list", "--json")):
                try:
                    rows = self._items(self._json_command(profile, *argv))
                    if rows:
                        return rows
                except Exception:
                    pass
        candidates = []
        home = self._profile_home(profile)
        for root in (home / "agents", home / "agent"):
            if root.exists():
                candidates.extend(p for p in root.iterdir() if p.is_dir())
        return [{"name": p.name, "path": str(p)} for p in sorted(candidates, key=lambda p: p.name.lower())]

    def agent_get(self, name: str, profile: str | None = None) -> dict[str, Any]:
        target = str(name or "").strip()
        if not target:
            raise ValueError("agent name is required")
        for row in self.agent_list(profile):
            if str(row.get("name") or row.get("id") or "").lower() == target.lower():
                return row
        raise KeyError(f"agent not found: {target}")

    def agent_create(self, payload: dict[str, Any], profile: str | None = None) -> Any:
        name = str(payload.get("name") or "").strip()
        if not name:
            raise ValueError("agent name is required")
        args = ["agent", "create", name]
        for key in ("model", "description"):
            value = str(payload.get(key) or "").strip()
            if value:
                args += [f"--{key}", value]
        return self._text_command(profile, *args)

    def agent_update(self, name: str, payload: dict[str, Any], profile: str | None = None) -> Any:
        args = ["agent", "update", name]
        for key, value in payload.items():
            if value is None:
                continue
            args += ["--" + str(key).replace("_", "-"), str(value)]
        return self._text_command(profile, *args)

    def agent_action(self, name: str, action: str, profile: str | None = None) -> Any:
        action = str(action or "").strip().lower()
        if action not in {"enable", "disable", "delete"}:
            raise ValueError("unsupported agent action")
        return self._text_command(profile, "agent", action, name)

    def project_list(self, profile: str | None = None) -> list[dict[str, Any]]:
        for argv in (("project", "list", "--json"), ("projects", "list", "--json")):
            try:
                return self._items(self._json_command(profile, *argv))
            except Exception:
                pass
        return []

    def project_get(self, name: str, profile: str | None = None) -> dict[str, Any]:
        target = str(name or "").strip()
        if not target:
            raise ValueError("project name is required")
        for row in self.project_list(profile):
            if str(row.get("name") or row.get("id") or "").lower() == target.lower():
                return row
        raise KeyError(f"project not found: {target}")

    def project_create(self, payload: dict[str, Any], profile: str | None = None) -> Any:
        name = str(payload.get("name") or "").strip()
        if not name:
            raise ValueError("project name is required")
        args = ["project", "create", name]
        path = str(payload.get("path") or "").strip()
        if path:
            args += ["--path", path]
        return self._text_command(profile, *args)

    def project_update(self, name: str, payload: dict[str, Any], profile: str | None = None) -> Any:
        args = ["project", "update", name]
        for key, value in payload.items():
            if value is None:
                continue
            args += ["--" + str(key).replace("_", "-"), str(value)]
        return self._text_command(profile, *args)

    def project_action(self, name: str, action: str, profile: str | None = None) -> Any:
        action = str(action or "").strip().lower()
        if action not in {"enable", "disable", "delete"}:
            raise ValueError("unsupported project action")
        return self._text_command(profile, "project", action, name)
