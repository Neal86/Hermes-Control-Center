from __future__ import annotations

import contextlib
import hashlib
import json
import os
import sys
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import Iterator

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from wechat.adapter import WeChatDesktop as _BaseWeChatDesktop, WeChatUnavailable  # noqa: E402


_UI_THREAD_LOCK = threading.RLock()
_LOCK_LOCAL = threading.local()


class _CrossProcessFileLock:
    """Small cross-process lock used to serialize WeChat UI side effects."""

    def __init__(self, path: Path, timeout: float = 15.0) -> None:
        self.path = path
        self.timeout = max(0.1, float(timeout))
        self._handle = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self.path, "a+b")
        if handle.seek(0, os.SEEK_END) == 0:
            handle.write(b"0")
            handle.flush()
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                self._handle = handle
                return
            except (OSError, BlockingIOError):
                if time.monotonic() >= deadline:
                    handle.close()
                    raise WeChatUnavailable(
                        "Timed out waiting for exclusive WeChat desktop access; refusing concurrent UI automation"
                    )
                time.sleep(0.05)

    def release(self) -> None:
        handle = self._handle
        self._handle = None
        if handle is None:
            return
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


class WeChatDesktop(_BaseWeChatDesktop):
    """Hardened runtime facade with cross-instance/process UI transactions."""

    def __init__(self, data_dir: Path | None = None, *, lock_timeout: float = 15.0) -> None:
        super().__init__(data_dir=data_dir)
        self._ui_lock_path = self.data_dir / "desktop-ui.lock"
        self._health_path = self.data_dir / "gateway-health.json"
        self._ui_lock_timeout = max(0.1, float(lock_timeout))

    @contextlib.contextmanager
    def _ui_transaction(self) -> Iterator[None]:
        depth = int(getattr(_LOCK_LOCAL, "depth", 0))
        if depth:
            _LOCK_LOCAL.depth = depth + 1
            try:
                yield
            finally:
                _LOCK_LOCAL.depth -= 1
            return

        acquired = _UI_THREAD_LOCK.acquire(timeout=self._ui_lock_timeout)
        if not acquired:
            raise WeChatUnavailable(
                "Timed out waiting for another local WeChat operation; refusing concurrent UI automation"
            )
        lock = _CrossProcessFileLock(self._ui_lock_path, self._ui_lock_timeout)
        try:
            lock.acquire()
            _LOCK_LOCAL.depth = 1
            try:
                yield
            finally:
                _LOCK_LOCAL.depth = 0
                lock.release()
        finally:
            _UI_THREAD_LOCK.release()

    def _gateway_health(self) -> dict | None:
        try:
            payload = json.loads(self._health_path.read_text("utf-8"))
            return payload if isinstance(payload, dict) else None
        except (OSError, json.JSONDecodeError):
            return None

    def status(self) -> dict:
        result = super().status()
        result["gateway_health"] = self._gateway_health()
        result["ui_lock_timeout_seconds"] = self._ui_lock_timeout
        return result

    def open_chat(self, chat: str) -> None:
        with self._ui_transaction():
            return super().open_chat(chat)

    def list_chats(self, limit: int = 50):
        with self._ui_transaction():
            return super().list_chats(limit)

    def unread_chats(self, limit: int = 50):
        with self._ui_transaction():
            return super().unread_chats(limit)

    def get_messages(self, chat: str, limit: int = 20) -> list[dict]:
        with self._ui_transaction():
            super().open_chat(chat)
            win = self._main_window()
            rows = self._message_rows(win, chat)
            compact: list[dict] = []
            occurrence: dict[tuple[str, str, str, str, str], int] = defaultdict(int)
            for row in rows:
                sender = str(row.get("sender") or "")
                shown_time = str(row.get("time") or "")
                direction = str(row.get("direction") or "")
                text = str(row.get("text") or "")
                base_identity = (chat, sender, text, shown_time, direction)
                ordinal = occurrence[base_identity]
                occurrence[base_identity] += 1
                identity_source = "\0".join([*base_identity, str(ordinal)])
                compact.append(
                    {
                        "text": text,
                        "sender": row.get("sender"),
                        "time": row.get("time"),
                        "direction": direction,
                        "message_id": hashlib.sha256(identity_source.encode("utf-8")).hexdigest()[:24],
                    }
                )
            return compact[-max(1, min(int(limit), 100)) :]

    def send_message(
        self,
        chat: str,
        text: str,
        *,
        dry_run: bool = False,
        duplicate_ttl: int = 600,
    ) -> dict:
        with self._ui_transaction():
            return super().send_message(
                chat,
                text,
                dry_run=dry_run,
                duplicate_ttl=duplicate_ttl,
            )
