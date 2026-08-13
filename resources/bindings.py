from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .context import root_hermes_home
from .registry import ResourceRegistry


class ResourceAccessError(RuntimeError):
    pass


class ResourceBindings:
    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or root_hermes_home() / "plugin-data" / "hermes-extensions" / "resources").expanduser()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "bindings.json"
        self.registry = ResourceRegistry(self.root)

    def _read(self) -> dict[str, str]:
        try:
            payload = json.loads(self.path.read_text("utf-8"))
            bindings = payload.get("bindings", {}) if isinstance(payload, dict) else {}
            return {str(k): str(v) for k, v in bindings.items() if k and v}
        except (OSError, json.JSONDecodeError):
            return {}

    def _write(self, bindings: dict[str, str]) -> None:
        fd, tmp = tempfile.mkstemp(prefix="bindings.", suffix=".json", dir=str(self.root))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump({"bindings": bindings}, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            Path(tmp).replace(self.path)
        finally:
            try:
                Path(tmp).unlink(missing_ok=True)
            except OSError:
                pass

    def list(self) -> dict[str, str]:
        return self._read()

    def bind(self, resource_id: str, agent: str) -> dict[str, Any]:
        resource = self.registry.get(resource_id, refresh=True)
        if not resource:
            raise ValueError("unknown desktop resource")
        agent = str(agent or "").strip().lower()
        if not agent:
            raise ValueError("agent is required")
        bindings = self._read()
        bindings[resource_id] = agent
        self._write(bindings)
        return {"resource": dict(resource, assigned_agent=agent), "agent": agent}

    def unbind(self, resource_id: str) -> bool:
        bindings = self._read()
        existed = resource_id in bindings
        bindings.pop(resource_id, None)
        self._write(bindings)
        return existed

    def resources_for_agent(self, agent: str, *, kind: str | None = None, refresh: bool = True) -> list[dict[str, Any]]:
        agent = str(agent or "").strip().lower()
        bindings = self._read()
        rows = self.registry.list(refresh=refresh)
        return [dict(row, assigned_agent=bindings.get(str(row.get("id")))) for row in rows if bindings.get(str(row.get("id"))) == agent and (kind is None or row.get("kind") == kind)]

    def require(self, agent: str, kind: str, *, ready: bool = True) -> dict[str, Any]:
        rows = self.resources_for_agent(agent, kind=kind, refresh=True)
        if not rows:
            raise ResourceAccessError(f"Agent '{agent}' has no bound {kind} resource")
        online = [row for row in rows if row.get("online")]
        if not online:
            raise ResourceAccessError(f"Agent '{agent}' bound {kind} resource is offline")
        if ready:
            usable = [row for row in online if row.get("status") == "ready"]
            if not usable:
                raise ResourceAccessError(f"Agent '{agent}' bound {kind} resource is not ready")
            return usable[0]
        return online[0]

    def authorize(self, agent: str, resource_id: str, *, kind: str | None = None, ready: bool = True) -> dict[str, Any]:
        agent = str(agent or "").strip().lower()
        bindings = self._read()
        if bindings.get(resource_id) != agent:
            raise ResourceAccessError(f"Resource '{resource_id}' is not bound to agent '{agent}'")
        resource = self.registry.get(resource_id, refresh=True)
        if not resource:
            raise ResourceAccessError("Bound resource no longer exists")
        if kind and resource.get("kind") != kind:
            raise ResourceAccessError(f"Resource '{resource_id}' is not a {kind} resource")
        if not resource.get("online"):
            raise ResourceAccessError("Bound resource is offline")
        if ready and resource.get("status") != "ready":
            raise ResourceAccessError("Bound resource is not ready")
        return dict(resource, assigned_agent=agent)
