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

from .adapter import WeChatDesktop as _BaseWeChatDesktop, WeChatUnavailable  # noqa: E402


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

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.release()
        return False


def _root_hermes_home() -> Path:
    raw = os.getenv("HERMES_HOME")
    if raw:
        home = Path(raw).expanduser()
    elif os.name == "nt" and os.getenv("LOCALAPPDATA"):
        home = Path(os.environ["LOCALAPPDATA"]) / "hermes"
    else:
        home = Path.home() / ".hermes"
    if home.name.startswith("profiles-"):
        return home.parent
    return home


def _resource_data_dir(resource_id: str | None) -> Path:
    root = _root_hermes_home() / "plugin-data" / "hermes-extensions" / "wechat"
    if resource_id:
        digest = hashlib.sha256(resource_id.encode("utf-8", errors="ignore")).hexdigest()[:24]
        root = root / digest
    root.mkdir(parents=True, exist_ok=True)
    return root


class WeChatDesktop(_BaseWeChatDesktop):
    """Hardened runtime facade with cross-instance/process UI transactions."""

    def __init__(self, data_dir: Path | None = None, *, lock_timeout: float = 15.0) -> None:
        super().__init__(data_dir=data_dir)
        self.lock_timeout = max(0.1, float(lock_timeout))
        self._lock_path = self.data_dir / "ui.lock"

    @contextlib.contextmanager
    def _ui_transaction(self) -> Iterator[None]:
        depth = int(getattr(_LOCK_LOCAL, "depth", 0))
        if depth > 0:
            _LOCK_LOCAL.depth = depth + 1
            try:
                yield
            finally:
                _LOCK_LOCAL.depth -= 1
            return
        with _UI_THREAD_LOCK:
            with _CrossProcessFileLock(self._lock_path, self.lock_timeout):
                _LOCK_LOCAL.depth = 1
                try:
                    yield
                finally:
                    _LOCK_LOCAL.depth = 0

    def status(self) -> dict:
        with self._ui_transaction():
            return super().status()

    def list_chats(self, limit: int = 200) -> list[dict]:
        with self._ui_transaction():
            return super().list_chats(limit=limit)

    def get_messages(self, chat: str, limit: int = 50) -> list[dict]:
        with self._ui_transaction():
            return super().get_messages(chat=chat, limit=limit)

    def send_message(self, chat: str, text: str, *, dry_run: bool = False) -> dict:
        with self._ui_transaction():
            return super().send_message(chat=chat, text=text, dry_run=dry_run)

    def get_unread_chats(self, limit: int = 200) -> list[dict]:
        with self._ui_transaction():
            return super().get_unread_chats(limit=limit)


def runtime_for_resource(resource_id: str | None) -> WeChatDesktop:
    return WeChatDesktop(_resource_data_dir(resource_id))
