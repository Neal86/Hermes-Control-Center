from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from resources.context import root_hermes_home


class ReceiverState:
    """Persistent receive cursor/dedup state scoped to one Agent."""

    def __init__(self, agent: str, path: Path | None = None) -> None:
        self.agent = str(agent or "").strip().lower() or "default"
        safe = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "-" for ch in self.agent)[:64]
        self.path = path or (
            root_hermes_home()
            / "plugin-data"
            / "hermes-extensions"
            / "wechat"
            / "receiver-state"
            / f"{safe}.json"
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = self._read()
        self.previews: dict[str, str] = dict(payload.get("previews", {}))
        self.messages: dict[str, dict[str, Any]] = dict(payload.get("messages", {}))

    def _read(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.path.read_text("utf-8"))
            return payload if isinstance(payload, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save(self) -> None:
        fd, temp_name = tempfile.mkstemp(prefix="receiver-state.", suffix=".json", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(
                    {"version": 1, "agent": self.agent, "previews": self.previews, "messages": self.messages},
                    handle,
                    ensure_ascii=False,
                    indent=2,
                )
                handle.write("\n")
            Path(temp_name).replace(self.path)
        finally:
            try:
                Path(temp_name).unlink(missing_ok=True)
            except OSError:
                pass

    @staticmethod
    def preview_fingerprint(chat: str, preview: str) -> str:
        return hashlib.sha256(f"{chat}\0{preview}".encode("utf-8")).hexdigest()

    def preview_changed(self, chat: str, preview: str) -> tuple[bool, str | None, str]:
        current = self.preview_fingerprint(chat, preview)
        previous = self.previews.get(chat)
        return previous != current, previous, current

    def commit_preview(self, chat: str, fingerprint: str) -> None:
        self.previews[chat] = fingerprint
        self._save()

    def seen_message(self, chat: str, fingerprint: str, ttl: float = 1200.0) -> bool:
        entry = self.messages.get(chat)
        if not isinstance(entry, dict):
            return False
        if str(entry.get("fingerprint") or "") != fingerprint:
            return False
        return time.time() - float(entry.get("at") or 0) < max(1.0, ttl)

    def commit_message(self, chat: str, fingerprint: str) -> None:
        now = time.time()
        self.messages[chat] = {"fingerprint": fingerprint, "at": now}
        cutoff = now - 86400.0
        self.messages = {
            key: value
            for key, value in self.messages.items()
            if isinstance(value, dict) and float(value.get("at") or 0) >= cutoff
        }
        self._save()
