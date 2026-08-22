from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

try:  # plugin package import
    from ..resources.context import root_hermes_home
except (ImportError, ValueError):  # source/platform import
    from resources.context import root_hermes_home


class ReceiverState:
    """Persistent receive cursor/dedup/echo state scoped to one Agent."""

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
        previews = payload.get("previews", {})
        messages = payload.get("messages", {})
        outbound = payload.get("outbound", {})
        db_cursors = payload.get("db_cursors", {})
        self.previews: dict[str, str] = dict(previews) if isinstance(previews, dict) else {}
        self.messages: dict[str, dict[str, Any]] = dict(messages) if isinstance(messages, dict) else {}
        self.outbound: dict[str, dict[str, Any]] = dict(outbound) if isinstance(outbound, dict) else {}
        self.db_cursors: dict[str, int] = {
            str(key): int(value)
            for key, value in (db_cursors.items() if isinstance(db_cursors, dict) else [])
            if str(key)
        }

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
                    {
                        "version": 3,
                        "agent": self.agent,
                        "previews": self.previews,
                        "messages": self.messages,
                        "outbound": self.outbound,
                        "db_cursors": self.db_cursors,
                    },
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

    def remember_outbound(self, chat: str, fingerprint: str) -> None:
        now = time.time()
        self.outbound[chat] = {"fingerprint": fingerprint, "at": now}
        cutoff = now - 3600.0
        self.outbound = {
            key: value
            for key, value in self.outbound.items()
            if isinstance(value, dict) and float(value.get("at") or 0) >= cutoff
        }
        self._save()

    def recent_outbound(self, chat: str, fingerprint: str, ttl: float = 60.0) -> bool:
        entry = self.outbound.get(chat)
        if not isinstance(entry, dict):
            return False
        if str(entry.get("fingerprint") or "") != fingerprint:
            return False
        return time.time() - float(entry.get("at") or 0) < max(1.0, ttl)

    def commit_db_cursor(self, conversation_id: str, sort_seq: int) -> None:
        key = str(conversation_id or "").strip()
        if not key:
            return
        self.db_cursors[key] = max(int(sort_seq or 0), int(self.db_cursors.get(key, 0)))
        self._save()

    def commit_db_cursors(self, cursors: dict[str, int]) -> None:
        changed = False
        for conversation_id, sort_seq in cursors.items():
            key = str(conversation_id or "").strip()
            value = int(sort_seq or 0)
            if key and value > int(self.db_cursors.get(key, 0)):
                self.db_cursors[key] = value
                changed = True
        if changed:
            self._save()
