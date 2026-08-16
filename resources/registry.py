from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from .context import root_hermes_home
from .discovery_v2 import discover_resources


class ResourceRegistry:
    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or root_hermes_home() / "plugin-data" / "hermes-extensions" / "resources").expanduser()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "resources.json"

    def _read(self) -> dict[str, dict[str, Any]]:
        try:
            raw = json.loads(self.path.read_text("utf-8"))
            rows = raw.get("resources", []) if isinstance(raw, dict) else []
            return {str(row.get("id")): row for row in rows if isinstance(row, dict) and row.get("id")}
        except (OSError, json.JSONDecodeError):
            return {}

    def _write(self, rows: list[dict[str, Any]]) -> None:
        payload = {"updated_at": int(time.time()), "resources": rows}
        fd, tmp = tempfile.mkstemp(prefix="resources.", suffix=".json", dir=str(self.root))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            Path(tmp).replace(self.path)
        finally:
            try:
                Path(tmp).unlink(missing_ok=True)
            except OSError:
                pass

    def refresh(self) -> list[dict[str, Any]]:
        previous = self._read()
        now = int(time.time())
        live = discover_resources()
        live_ids = {row["id"] for row in live}
        merged: list[dict[str, Any]] = []
        for row in live:
            old = previous.get(row["id"], {})
            enriched = dict(old)
            enriched.update(row)
            enriched["last_seen_at"] = now
            enriched["online"] = True
            merged.append(enriched)
        for resource_id, old in previous.items():
            if resource_id in live_ids:
                continue
            stale = dict(old)
            stale["online"] = False
            stale["status"] = "offline"
            merged.append(stale)
        merged.sort(key=lambda item: (str(item.get("kind")), str(item.get("app")), str(item.get("title", "")).lower()))
        self._write(merged)
        return merged

    def list(self, *, refresh: bool = False) -> list[dict[str, Any]]:
        if refresh or not self.path.exists():
            return self.refresh()
        return list(self._read().values())

    def get(self, resource_id: str, *, refresh: bool = False) -> dict[str, Any] | None:
        return next((row for row in self.list(refresh=refresh) if row.get("id") == resource_id), None)
