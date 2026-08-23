from __future__ import annotations

import contextlib
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
import re
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
_STATUS_PREFIX_RE = re.compile(
    r"^\s*(?:已置顶\s*)?(?:(?:[\[【(（]\s*\d+\s*条\s*[\]】)）])\s*)+",
    re.IGNORECASE,
)


def _thread_lock(resource_id: str) -> threading.RLock:
    with _LOCKS_GUARD:
        return _RESOURCE_LOCKS.setdefault(resource_id, threading.RLock())


class BoundWeChatDesktop(_RuntimeWeChat):
    """WeChat runtime pinned to one Agent resource with foreground restoration.

    Polling keeps using read-only UIA. A changed conversation is switched only by
    posting window-local mouse messages to the exact bound WeChat HWND at the
    current UIA session item's live rectangle. The physical mouse is never moved,
    fixed screen coordinates are never used, and the resulting chat header must
    match exactly before any read or send may continue. No resize, search fallback,
    foreground input, or alternate WeChat instance is allowed.
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

    def _restore_previous_foreground(self, *, before: int, operation: str) -> None:
        """Put the user's original app back if WeChat stole foreground.

        SelectionItem.Select is the only known UIA operation here that may make
        modern WeChat foreground. We intentionally allow the selection to finish,
        then restore the pre-operation foreground HWND immediately. This avoids
        retry loops that would repeatedly steal focus on every poll.
        """
        if os.name != "nt" or not before or before == self.window_handle:
            return
        after = self._foreground_hwnd()
        if after != self.window_handle:
            return
        self._record_focus_violation(before=before, after=after, operation=operation)
        try:
            self._restore_foreground(int(before))
        except Exception:
            pass
        # Do not throw here. The message read/send may already have succeeded;
        # throwing would leave its preview uncommitted and cause the same chat to
        # be retried on every polling cycle, producing repeated focus changes.

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
        """Serialize UIA access and restore the user's foreground app afterward."""
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
            self._restore_previous_foreground(before=before, operation="ui_transaction")

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
                    re.search(r"[\[【(（]\s*\d+\s*条\s*[\]】)）]", text)
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

    @staticmethod
    def _session_selected(control) -> bool:
        """Read SelectionItem.CurrentIsSelected without changing the UI."""
        try:
            return bool(control.iface_selection_item.CurrentIsSelected)
        except Exception:
            return False

    @staticmethod
    def _current_chat_header(win) -> str:
        """Read modern WeChat's canonical current-chat header, if exposed."""
        names: list[str] = []
        try:
            controls = win.descendants(control_type="Text")
        except Exception:
            return ""
        for control in controls:
            try:
                automation_id = str(getattr(control.element_info, "automation_id", "") or "")
                if not automation_id.endswith("current_chat_name_label"):
                    continue
                value = str(control.window_text() or "").strip()
                if value and value not in names:
                    names.append(value)
            except Exception:
                continue
        return names[0] if len(names) == 1 else ""

    def _is_current_target(self, win, chat: str) -> bool:
        """Fail closed on the canonical header before weaker UIA evidence."""
        wanted = str(chat or "").strip()
        if not wanted:
            return False
        header = self._current_chat_header(win)
        if header:
            return header == wanted
        try:
            if super()._is_current_target(win, wanted):
                return True
        except Exception:
            pass
        matches = self._session_matches(win, wanted)
        return len(matches) == 1 and self._session_selected(matches[0])

    def _post_session_click(self, control, *, chat: str) -> None:
        """Post a dynamic, window-local click without moving the physical mouse."""
        if os.name != "nt":
            raise WeChatUnavailable("BACKGROUND_SEND_UNSUPPORTED: window-message switching requires Windows")
        try:
            rect = control.rectangle()
            win = self._main_window()
            win_rect = win.rectangle()
            x_screen = (int(rect.left) + int(rect.right)) // 2
            y_screen = (int(rect.top) + int(rect.bottom)) // 2
            if not (
                int(win_rect.left) <= x_screen < int(win_rect.right)
                and int(win_rect.top) <= y_screen < int(win_rect.bottom)
            ):
                raise WeChatUnavailable(f"Session {chat!r} is outside the bound WeChat window")
            point = wintypes.POINT(x_screen, y_screen)
            user32 = ctypes.windll.user32
            if not user32.ScreenToClient(int(self.window_handle), ctypes.byref(point)):
                raise ctypes.WinError()
            lparam = ((int(point.y) & 0xFFFF) << 16) | (int(point.x) & 0xFFFF)
            messages = (
                (0x0200, 0),
                (0x0201, 0x0001),
                (0x0202, 0),
            )
            for message, wparam in messages:
                if not user32.PostMessageW(int(self.window_handle), message, wparam, lparam):
                    raise ctypes.WinError()
        except WeChatUnavailable:
            raise
        except Exception as exc:
            raise WeChatUnavailable(f"BACKGROUND_SEND_UNSUPPORTED: failed to switch session {chat!r}: {exc}") from exc

    def _select_session_background(self, control, *, chat: str) -> None:
        """Switch only inside the bound HWND and require the real header to confirm it."""
        before = self._foreground_hwnd()
        self._post_session_click(control, chat=chat)
        deadline = time.monotonic() + 1.5
        while time.monotonic() < deadline:
            time.sleep(0.05)
            if self._current_chat_header(self._main_window()) == chat:
                self._restore_previous_foreground(before=before, operation=f"select_session:{chat}")
                return
        self._restore_previous_foreground(before=before, operation=f"select_session:{chat}")
        raise WeChatUnavailable(f"Target verification failed after background switching {chat!r}")

    def open_chat(self, chat: str) -> None:
        """Open a chat from the bound WeChat session list only."""
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
                "strict mode will not search, resize, activate, click, or switch to another WeChat instance"
            )
        self._select_session_background(matches[0], chat=chat)
        win = self._main_window()
        if not self._is_current_target(win, chat):
            raise WeChatUnavailable(f"Target verification failed after selecting {chat!r}")

    @staticmethod
    def _clean_message_text(text: str) -> str:
        value = str(text or "").strip()
        previous = None
        while value and value != previous:
            previous = value
            value = _STATUS_PREFIX_RE.sub("", value).strip()
        return value

    def get_messages(self, chat: str, limit: int = 50) -> list[dict[str, Any]]:
        """Deep-read the exact chat and remove session UI status prefixes."""
        rows = super().get_messages(chat=chat, limit=limit)
        cleaned: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["text"] = self._clean_message_text(item.get("text") or "")
            if not item["text"]:
                continue
            cleaned.append(item)
        return cleaned

    def status(self) -> dict:
        result = super().status()
        result.update(
            {
                "agent": self.agent,
                "resource_id": self.resource_id,
                "bound": True,
                "window_handle": self.window_handle,
                "strict_background": True,
                "read_only_receive": False,
                "background_chat_selection": True,
                "background_switch_transport": "bound-hwnd-window-message",
                "canonical_header_verification": True,
                "selected_state_verification": False,
                "restore_previous_foreground": True,
                "foreground_fallback": False,
                "window_resize_allowed": False,
                "window_move_allowed": False,
                "invoke_allowed": False,
                "physical_input_allowed": False,
            }
        )
        return result
