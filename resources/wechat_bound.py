from __future__ import annotations

import contextlib
import ctypes
import hashlib
import json
import os
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from wechat.adapter import ChatRow
from wechat.runtime import WeChatDesktop as _RuntimeWeChat, WeChatUnavailable, _CrossProcessFileLock

from .bindings import ResourceBindings

_LOCKS_GUARD = threading.Lock()
_RESOURCE_LOCKS: dict[str, threading.RLock] = {}
_LOCAL = threading.local()


def _thread_lock(resource_id: str) -> threading.RLock:
    with _LOCKS_GUARD:
        return _RESOURCE_LOCKS.setdefault(resource_id, threading.RLock())


class BoundWeChatDesktop(_RuntimeWeChat):
    """Strict background-only WeChat runtime pinned to one Agent resource.

    Receive operations are read-only UIA tree scans. Send operations may change
    the selected WeChat conversation through SelectionItem, but never call
    Invoke/click, SetForegroundWindow, BringWindowToTop, ShowWindow, SetWindowPos,
    or physical keyboard/mouse input. If the bound WeChat window is minimized or
    the target session cannot be selected through background UIA patterns, the
    operation fails closed instead of taking over the user's desktop.
    """

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
        self._ui_lock_timeout = self.lock_timeout
        self._ui_lock_path = self.data_dir / "desktop-ui.lock"
        self._focus_audit_path = self.data_dir / "focus-audit.jsonl"

    @staticmethod
    def _foreground_hwnd() -> int:
        if os.name != "nt":
            return 0
        try:
            return int(ctypes.windll.user32.GetForegroundWindow() or 0)
        except Exception:
            return 0

    def _record_focus_violation(self, *, before: int, after: int, operation: str) -> None:
        try:
            payload = {
                "timestamp": datetime.now(UTC).isoformat(),
                "operation": operation,
                "before_hwnd": before,
                "after_hwnd": after,
                "wechat_hwnd": self.window_handle,
                "resource_id": self.resource_id,
                "agent": self.agent,
            }
            self._focus_audit_path.parent.mkdir(parents=True, exist_ok=True)
            with self._focus_audit_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def _assert_no_focus_takeover(self, *, before: int, operation: str) -> None:
        if os.name != "nt" or not before:
            return
        after = self._foreground_hwnd()
        if after == self.window_handle and before != self.window_handle:
            self._record_focus_violation(before=before, after=after, operation=operation)
            raise WeChatUnavailable(
                f"BACKGROUND_FOCUS_VIOLATION during {operation}; refusing foreground fallback"
            )

    def _main_window(self):
        Desktop = self._deps()
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
        """Serialize UIA access without any foreground restoration side effects."""
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

        before = self._foreground_hwnd()
        lock = _thread_lock(key)
        acquired = lock.acquire(timeout=self._ui_lock_timeout)
        if not acquired:
            raise WeChatUnavailable("Timed out waiting for the bound WeChat resource")
        process_lock = _CrossProcessFileLock(self._ui_lock_path, self._ui_lock_timeout)
        completed = False
        try:
            process_lock.acquire()
            depths[key] = 1
            try:
                yield
                completed = True
            finally:
                depths[key] = 0
                process_lock.release()
        finally:
            lock.release()
        if completed:
            self._assert_no_focus_takeover(before=before, operation="ui_transaction")

    def list_chats(self, limit: int = 200) -> list[ChatRow]:
        """Read the existing session list without resizing, moving, or activating WeChat."""
        with self._ui_transaction():
            win = self._main_window()
            rows: list[ChatRow] = []
            seen: set[str] = set()
            try:
                lists = win.descendants(control_type="List")
                if not any(
                    str(getattr(control.element_info, "automation_id", "") or "") == "session_list"
                    for control in lists
                ):
                    raise WeChatUnavailable(
                        "WeChat session list is not exposed in the current window layout; "
                        "strict background mode will not resize or activate the window"
                    )
                all_candidates = win.descendants(control_type="ListItem")
                candidates = [
                    control
                    for control in all_candidates
                    if str(getattr(control.element_info, "automation_id", "") or "").startswith("session_item_")
                ]
                if not candidates:
                    raise WeChatUnavailable("No WeChat session items are exposed through UI Automation")
            except WeChatUnavailable:
                raise
            except Exception as exc:
                raise WeChatUnavailable(f"Unable to enumerate WeChat conversation list: {exc}") from exc

            for control in candidates:
                text = self._text(control)
                if not text:
                    continue
                try:
                    text_children = [
                        (item.window_text() or "").strip()
                        for item in control.descendants(control_type="Text")
                        if (item.window_text() or "").strip()
                    ]
                except Exception:
                    text_children = []
                own_lines = [line.strip() for line in self._safe_text(control).splitlines() if line.strip()]
                name = text_children[0] if text_children else (own_lines[0] if own_lines else "")
                if not name or name in seen:
                    continue
                lower = text.lower()
                unread = any(marker.lower() in lower for marker in self.UNREAD_MARKERS) or bool(
                    __import__("re").search(r"[\[【(（]\s*\d+\s*条\s*[\]】)）]", text)
                )
                preview_parts = text_children[1:3] if len(text_children) > 1 else own_lines[1:4]
                preview = " ".join(preview_parts)
                rows.append(ChatRow(name=name, unread=unread, preview=preview))
                seen.add(name)
                if len(rows) >= max(1, min(int(limit), 200)):
                    break
            return rows

    def get_unread_chats(self, limit: int = 200) -> list[dict[str, Any]]:
        return [row.to_dict() for row in self.unread_chats(limit=limit)]

    def _session_matches(self, win, chat: str) -> list[Any]:
        wanted = chat.strip()
        matches: list[Any] = []
        seen_controls: set[str] = set()
        try:
            items = win.descendants(control_type="ListItem")
        except Exception:
            return []
        for item in items:
            try:
                automation_id = str(getattr(item.element_info, "automation_id", "") or "")
                if not automation_id.startswith("session_item_"):
                    continue
                labels = [
                    self._safe_text(child)
                    for child in item.descendants(control_type="Text")
                    if self._safe_text(child)
                ]
                own = self._safe_text(item)
                if own:
                    labels[:0] = [line.strip() for line in own.splitlines() if line.strip()]
                if wanted not in labels:
                    continue
                runtime_id = getattr(item.element_info, "runtime_id", None)
                control_key = repr(tuple(runtime_id)) if runtime_id else repr(item.rectangle())
                if control_key not in seen_controls:
                    matches.append(item)
                    seen_controls.add(control_key)
            except Exception:
                continue
        return matches

    def _select_session_background(self, control, *, chat: str) -> None:
        """Select one session using UIA SelectionItem only; never Invoke or click."""
        before = self._foreground_hwnd()
        try:
            if hasattr(control, "select"):
                control.select()
            else:
                control.iface_selection_item.Select()
        except Exception as exc:
            raise WeChatUnavailable(
                f"BACKGROUND_SEND_UNSUPPORTED: WeChat session {chat!r} has no background SelectionItem pattern"
            ) from exc
        time.sleep(0.2)
        self._assert_no_focus_takeover(before=before, operation=f"select_session:{chat}")

    def open_chat(self, chat: str) -> None:
        """Open a chat in the background from the existing session list only."""
        chat = chat.strip()
        if not chat:
            raise ValueError("chat is required")
        win = self._main_window()
        if self._is_current_target(win, chat):
            return
        matches = self._session_matches(win, chat)
        if len(matches) > 1:
            raise WeChatUnavailable(f"Ambiguous WeChat session title: {chat!r}")
        if not matches:
            raise WeChatUnavailable(
                f"BACKGROUND_SEND_UNSUPPORTED: session {chat!r} is not exposed in the current session list; "
                "strict background mode will not search, resize, activate, or click the WeChat window"
            )
        self._select_session_background(matches[0], chat=chat)
        win = self._main_window()
        if not self._is_current_target(win, chat):
            raise WeChatUnavailable(f"Background target verification failed after selecting {chat!r}")

    def status(self) -> dict:
        result = super().status()
        result.update(
            {
                "agent": self.agent,
                "resource_id": self.resource_id,
                "bound": True,
                "window_handle": self.window_handle,
                "strict_background": True,
                "read_only_receive": True,
                "foreground_fallback": False,
                "window_resize_allowed": False,
                "window_move_allowed": False,
                "invoke_allowed": False,
                "physical_input_allowed": False,
            }
        )
        return result
