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
    """Compatibility store for runtime resource ownership.

    Domain-specific restart recovery belongs to wechat.binding/browser.binding;
    this class preserves the existing Dashboard/API contract.
    """

    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or root_hermes_home() / "plugin-data" / "hermes-extensions" / "resources").expanduser()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "bindings.json"
        self.registry = ResourceRegistry(self.root)

    def _read(self) -> dict[str, str]:
        try:
            payload = json.loads(self.path.read_text("utf-8"))
            bindings = payload.get("bindings", {}) if isinstance(payload, dict) else {}
            return {str(k): str(v).strip().lower() for k, v in bindings.items() if k and v}
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
        if not resource.get("online"):
            raise ValueError("desktop resource is offline")
        agent = str(agent or "").strip().lower()
        if not agent:
            raise ValueError("agent is required")
        kind = str(resource.get("kind") or "").strip().lower()
        if not kind:
            raise ValueError("desktop resource has no kind")

        bindings = self._read()
        rows = {str(row.get("id")): row for row in self.registry.list(refresh=False)}
        replaced: list[str] = []
        for existing_id, existing_agent in list(bindings.items()):
            if existing_id == resource_id or existing_agent != agent:
                continue
            existing = rows.get(existing_id)
            if existing and str(existing.get("kind") or "").strip().lower() == kind:
                bindings.pop(existing_id, None)
                replaced.append(existing_id)
        bindings[resource_id] = agent
        self._write(bindings)
        return {"resource": dict(resource, assigned_agent=agent), "agent": agent, "replaced": replaced}

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
        return [
            dict(row, assigned_agent=bindings.get(str(row.get("id"))))
            for row in rows
            if bindings.get(str(row.get("id"))) == agent
            and (kind is None or row.get("kind") == kind)
        ]

    def require(self, agent: str, kind: str, *, ready: bool = True) -> dict[str, Any]:
        rows = self.resources_for_agent(agent, kind=kind, refresh=True)
        if not rows:
            raise ResourceAccessError(f"Agent '{agent}' has no bound {kind} resource")
        if len(rows) > 1:
            raise ResourceAccessError(
                f"Agent '{agent}' has multiple bound {kind} resources; rebind one resource to repair the ambiguous state"
            )
        row = rows[0]
        if not row.get("online"):
            # WeChat recovery is intentionally delegated to WeChatBindingService,
            # which has restart-stable hints and can fail closed on ambiguity.
            if str(kind).strip().lower() == "wechat":
                raise ResourceAccessError(f"Agent '{agent}' bound wechat resource is offline")

            bindings = self._read()
            live = [
                candidate
                for candidate in self.registry.list(refresh=False)
                if candidate.get("kind") == kind
                and candidate.get("online")
                and (not ready or candidate.get("status") == "ready")
                and not bindings.get(str(candidate.get("id")))
            ]
            if len(live) == 1:
                replacement = live[0]
                bindings.pop(str(row.get("id")), None)
                bindings[str(replacement["id"])] = agent
                self._write(bindings)
                return dict(replacement, assigned_agent=agent, rebound_from=str(row.get("id")))
            raise ResourceAccessError(
                f"Agent '{agent}' bound {kind} resource is offline; found {len(live)} unbound live replacement(s)"
            )
        if ready and row.get("status") != "ready":
            raise ResourceAccessError(f"Agent '{agent}' bound {kind} resource is not ready")
        return row

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
