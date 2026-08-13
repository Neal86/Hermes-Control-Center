from __future__ import annotations

import contextlib
import hashlib
import os
import threading
from pathlib import Path
from typing import Iterator

from wechat.runtime import WeChatDesktop as _RuntimeWeChat, WeChatUnavailable, _CrossProcessFileLock

from .bindings import ResourceBindings

_LOCKS_GUARD = threading.Lock()
_RESOURCE_LOCKS: dict[str, threading.RLock] = {}
_LOCAL = threading.local()


def _thread_lock(resource_id: str) -> threading.RLock:
    with _LOCKS_GUARD:
        return _RESOURCE_LOCKS.setdefault(resource_id, threading.RLock())


class BoundWeChatDesktop(_RuntimeWeChat):
    """WeChat runtime pinned to exactly one resource assigned to one Agent."""

    def __init__(self, agent: str, resource_id: str | None = None, *, lock_timeout: float = 15.0) -> None:
        self.agent = str(agent or "").strip()
        if not self.agent:
            raise ValueError("agent is required")
        self.bindings = ResourceBindings()
        resource = (
            self.bindings.authorize(self.agent, str(resource_id), kind="wechat", ready=True)
            if resource_id
            else self.bindings.require(self.agent, "wechat", ready=True)
        )
        self.resource = resource
        self.resource_id = str(resource["id"])
        self.window_handle = int(resource.get("hwnd") or 0)
        if not self.window_handle:
            raise WeChatUnavailable("Bound WeChat resource has no usable window handle")
        hermes_home = Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")
        digest = hashlib.sha256(self.resource_id.encode("utf-8")).hexdigest()[:16]
        data_dir = hermes_home / "plugin-data" / "hermes-extensions" / "wechat" / "instances" / digest
        super().__init__(data_dir=data_dir, lock_timeout=lock_timeout)
        self._ui_lock_path = self.data_dir / "desktop-ui.lock"

    def _main_window(self):
        Desktop, _, _ = self._deps()
        try:
            win = Desktop(backend="uia").window(handle=self.window_handle)
            if not win.exists(timeout=0.5) or not win.is_visible():
                raise WeChatUnavailable("Bound WeChat window is no longer available")
            self._restore_window(win)
            return win
        except WeChatUnavailable:
            raise
        except Exception as exc:
            raise WeChatUnavailable(f"Unable to attach bound WeChat window: {exc}") from exc

    @contextlib.contextmanager
    def _ui_transaction(self) -> Iterator[None]:
        key = self.resource_id
        depths = getattr(_LOCAL, "depths", None)
        if depths is None:
            depths = {}
            _LOCAL.depths = depths
        depth = int(depths.get(key, 0))
        if depth:
            depths[key] = depth + 1
            try:
                yield
            finally:
                depths[key] -= 1
            return
        lock = _thread_lock(key)
        acquired = lock.acquire(timeout=self._ui_lock_timeout)
        if not acquired:
            raise WeChatUnavailable("Timed out waiting for the bound WeChat resource")
        process_lock = _CrossProcessFileLock(self._ui_lock_path, self._ui_lock_timeout)
        try:
            process_lock.acquire()
            depths[key] = 1
            try:
                yield
            finally:
                depths[key] = 0
                process_lock.release()
        finally:
            lock.release()

    def status(self) -> dict:
        result = super().status()
        result.update({
            "agent": self.agent,
            "resource_id": self.resource_id,
            "bound": True,
            "window_handle": self.window_handle,
        })
        return result
