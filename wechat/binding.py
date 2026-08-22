from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from resources.bindings import ResourceAccessError, ResourceBindings
from resources.context import root_hermes_home

from .identity import compatible_resource, normalize_agent, resource_hints, stable_binding_id


class WeChatBindingService:
    """Own Agent-to-WeChat binding and conservative restart recovery.

    resources/bindings.json stays compatible with the existing Dashboard. A
    separate logical record keeps restart-stable hints so a volatile runtime
    resource id may be replaced without guessing between multiple candidates.
    """

    def __init__(self, root: Path | None = None) -> None:
        self.bindings = ResourceBindings(root)
        base = root or root_hermes_home() / "plugin-data" / "hermes-extensions" / "resources"
        self.path = Path(base).expanduser() / "wechat-bindings-v2.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _read(self) -> dict[str, dict[str, Any]]:
        try:
            payload = json.loads(self.path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        records = payload.get("records", {}) if isinstance(payload, dict) else {}
        return {str(key): dict(value) for key, value in records.items() if isinstance(value, dict)}

    def _write(self, records: dict[str, dict[str, Any]]) -> None:
        fd, temp_name = tempfile.mkstemp(prefix="wechat-bindings.", suffix=".json", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump({"version": 2, "records": records}, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            Path(temp_name).replace(self.path)
        finally:
            try:
                Path(temp_name).unlink(missing_ok=True)
            except OSError:
                pass

    def _remember(self, agent: str, resource: dict[str, Any]) -> dict[str, Any]:
        agent = normalize_agent(agent)
        binding_id = stable_binding_id(agent)
        records = self._read()
        record = {
            "binding_id": binding_id,
            "agent": agent,
            "kind": "wechat",
            "runtime_resource_id": str(resource.get("id") or ""),
            "hints": resource_hints(resource),
            "needs_rebind": False,
            "candidate_count": 0,
        }
        records[binding_id] = record
        self._write(records)
        return record

    def bind(self, resource_id: str, agent: str) -> dict[str, Any]:
        agent = normalize_agent(agent)
        result = self.bindings.bind(resource_id, agent)
        if str(result["resource"].get("kind") or "").lower() == "wechat":
            self._remember(agent, result["resource"])
        return result

    def unbind(self, resource_id: str) -> bool:
        current = self.bindings.list()
        agent = current.get(resource_id)
        existed = self.bindings.unbind(resource_id)
        if agent:
            records = self._read()
            records.pop(stable_binding_id(agent), None)
            self._write(records)
        return existed

    def require(self, agent: str, *, ready: bool = True) -> dict[str, Any]:
        agent = normalize_agent(agent)
        try:
            resource = self.bindings.require(agent, "wechat", ready=ready)
            self._remember(agent, resource)
            return resource
        except ResourceAccessError as direct_error:
            records = self._read()
            key = stable_binding_id(agent)
            record = records.get(key)
            if not record:
                # Legacy state has no safe restart-stable hints yet. Do not guess
                # among multiple WeChat windows merely to manufacture a migration.
                raise direct_error

        ownership = self.bindings.list()
        live = [
            row
            for row in self.bindings.registry.list(refresh=True)
            if row.get("kind") == "wechat"
            and row.get("online")
            and (not ready or row.get("status") == "ready")
            and not ownership.get(str(row.get("id")))
            and compatible_resource(record, row)
        ]
        if len(live) != 1:
            record = dict(record)
            record["needs_rebind"] = True
            record["candidate_count"] = len(live)
            records[key] = record
            self._write(records)
            raise ResourceAccessError(
                f"Agent '{agent}' bound wechat resource is offline; found {len(live)} compatible "
                "unbound live replacement(s); explicit rebind required"
            )

        replacement = live[0]
        old_runtime = str(record.get("runtime_resource_id") or "")
        result = self.bindings.bind(str(replacement["id"]), agent)
        remembered = self._remember(agent, result["resource"])
        return dict(
            result["resource"],
            rebound_from=old_runtime,
            stable_binding_id=remembered["binding_id"],
        )
