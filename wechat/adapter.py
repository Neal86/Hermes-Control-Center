from __future__ import annotations

import hashlib
import json
import os
import platform
import ctypes
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class WeChatUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class ChatRow:
    name: str
    unread: bool = False
    preview: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "unread": self.unread, "preview": self.preview}


class WeChatDesktop:
    """Windows WeChat UI Automation adapter with fail-closed send semantics.

    The adapter never relies on fixed screen coordinates. Before every send it
    resolves the requested chat through the UIA tree, rejects ambiguous search
    results, opens the exact conversation, and verifies the visible title again
    immediately before the Enter key side effect.
    """

    WINDOW_MARKERS = ("微信", "WeChat")
    UNREAD_MARKERS = ("条新消息", "new message", "unread", "未读")
    TIME_MARKERS = ("AM", "PM", "上午", "下午", ":")

    def __init__(self, data_dir: Path | None = None) -> None:
        hermes_home = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
        self.data_dir = data_dir or hermes_home / "plugin-data" / "hermes-extensions" / "wechat"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._state_path = self.data_dir / "send-state.json"
        self._lock = threading.RLock()

    @staticmethod
    def available() -> bool:
        if platform.system() != "Windows":
            return False
        try:
            import pywinauto  # noqa: F401
        except Exception:
            return False
        return True

    @staticmethod
    def _deps():
        if platform.system() != "Windows":
            raise WeChatUnavailable("wechat-desktop requires native Windows")
        try:
            from pywinauto import Desktop
        except Exception as exc:
            raise WeChatUnavailable(
                "Missing Windows dependency. Install: pip install pywinauto"
            ) from exc
        return Desktop

    @staticmethod
    def _safe_text(control) -> str:
        try:
            return (control.window_text() or "").strip()
        except Exception:
            return ""

    @staticmethod
    def _rect_area(control) -> int:
        try:
            rect = control.rectangle()
            return max(0, rect.width()) * max(0, rect.height())
        except Exception:
            return 0

    def _restore_window(self, win) -> None:
        """Validate background availability without changing desktop state.

        Restoring or focusing the window would switch the user's foreground
        application. Strict background mode therefore fails closed when WeChat
        is minimized instead of silently taking over the desktop.
        """
        try:
            if hasattr(win, "is_minimized") and win.is_minimized():
                raise WeChatUnavailable(
                    "Bound WeChat window is minimized; background-only mode will not restore or focus it"
                )
        except WeChatUnavailable:
            raise
        except Exception as exc:
            raise WeChatUnavailable(f"Unable to verify WeChat background state: {exc}") from exc

    def _main_window(self):
        Desktop = self._deps()
        candidates = []
        for win in Desktop(backend="uia").windows():
            try:
                title = self._safe_text(win)
                if not title or not win.is_visible():
                    continue
                if any(marker.lower() in title.lower() for marker in self.WINDOW_MARKERS):
                    candidates.append((self._rect_area(win), win))
            except Exception:
                continue
        if not candidates:
            raise WeChatUnavailable("No visible Windows WeChat window was found")
        candidates.sort(key=lambda row: row[0], reverse=True)
        win = candidates[0][1]
        self._restore_window(win)
        return win

    @staticmethod
    def _text(control) -> str:
        parts: list[str] = []
        try:
            value = (control.window_text() or "").strip()
            if value:
                parts.append(value)
        except Exception:
            pass
        try:
            for child in control.descendants(control_type="Text"):
                value = (child.window_text() or "").strip()
                if value and value not in parts:
                    parts.append(value)
        except Exception:
            pass
        return " ".join(parts).strip()

    def status(self) -> dict[str, Any]:
        if not self.available():
            return {
                "available": False,
                "platform": platform.system(),
                "reason": "Requires native Windows plus pywinauto",
                "transport": "windows-uia",
                "fail_closed_send": True,
                "background_only": True,
                "foreground_fallback": False,
            }
        try:
            win = self._main_window()
            return {
                "available": True,
                "window_title": self._safe_text(win),
                "window_handle": int(win.handle),
                "backend": "uia",
                "transport": "windows-uia",
                "fail_closed_send": True,
                "background_only": True,
                "foreground_fallback": False,
            }
        except Exception as exc:
            return {
                "available": False,
                "platform": platform.system(),
                "reason": str(exc),
                "transport": "windows-uia",
                "fail_closed_send": True,
                "background_only": True,
                "foreground_fallback": False,
            }

    def list_chats(self, limit: int = 50) -> list[ChatRow]:
        win = self._main_window()
        # New WeChat hides the session list when the window is too narrow.
        # Expand the bound window without activating it so background polling
        # can still observe unread conversations.
        try:
            has_session_list = any(
                str(control.element_info.automation_id or "") == "session_list"
                for control in win.descendants(control_type="List")
            )
            rect = win.rectangle()
            if not has_session_list and rect.width() < 1050 and platform.system() == "Windows":
                user32 = ctypes.windll.user32
                screen_width = int(user32.GetSystemMetrics(0) or 1920)
                left = max(0, min(int(rect.left), max(0, screen_width - 1200)))
                user32.SetWindowPos(
                    int(win.handle), 0, left, max(0, int(rect.top)), 1200,
                    max(800, int(rect.height())), 0x0004 | 0x0010,
                )  # SWP_NOZORDER | SWP_NOACTIVATE
                time.sleep(0.3)
                win = self._main_window()
        except Exception:
            pass
        rows: list[ChatRow] = []
        seen: set[str] = set()
        try:
            all_candidates = win.descendants(control_type="ListItem")
            candidates = [
                control for control in all_candidates
                if str(control.element_info.automation_id or "").startswith("session_item_")
            ]
            if not candidates:
                raise WeChatUnavailable(
                    "WeChat session list is hidden; widen the bound main window"
                )
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

    def unread_chats(self, limit: int = 50) -> list[ChatRow]:
        return [row for row in self.list_chats(limit=200) if row.unread][: max(1, min(int(limit), 200))]

    def _search_edit(self, win):
        rect = win.rectangle()
        edits = []
        for edit in win.descendants(control_type="Edit"):
            try:
                er = edit.rectangle()
                if not edit.is_visible() or not edit.is_enabled():
                    continue
                if er.top <= rect.top + max(180, rect.height() // 4):
                    edits.append((er.top, -er.width(), edit))
            except Exception:
                continue
        if not edits:
            raise WeChatUnavailable("Could not locate WeChat search field through UI Automation")
        edits.sort(key=lambda row: (row[0], row[1]))
        return edits[0][2]

    @staticmethod
    def _set_text(control, text: str) -> None:
        """Write through UI Automation's Value pattern, never global input."""
        try:
            control.iface_value.SetValue(text)
        except Exception as exc:
            raise WeChatUnavailable(
                "This WeChat control does not expose background text input; foreground fallback is disabled"
            ) from exc

    @staticmethod
    def _invoke(control) -> None:
        """Invoke a UIA control without moving the physical mouse."""
        try:
            if hasattr(control, "invoke"):
                control.invoke()
            else:
                control.iface_invoke.Invoke()
        except Exception as exc:
            raise WeChatUnavailable(
                "This WeChat control does not expose a background action; foreground fallback is disabled"
            ) from exc

    @staticmethod
    def _post_enter(editor) -> None:
        """Post Enter directly to the bound WeChat HWND without focus or mouse input."""
        try:
            hwnd = int(editor.top_level_parent().handle)
            user32 = ctypes.windll.user32
            key_down = user32.PostMessageW(hwnd, 0x0100, 0x0D, 0x001C0001)
            key_up = user32.PostMessageW(hwnd, 0x0101, 0x0D, 0xC01C0001)
            if not key_down or not key_up:
                raise OSError("PostMessageW returned false")
        except Exception as exc:
            raise WeChatUnavailable(
                "WeChat does not accept background Enter delivery; foreground fallback is disabled"
            ) from exc

    @staticmethod
    def _editor_value(editor) -> str:
        """Read the UIA Value pattern without focusing the editor."""
        try:
            if hasattr(editor, "get_value"):
                return str(editor.get_value() or "")
        except Exception:
            pass
        try:
            return str(editor.iface_value.CurrentValue or "")
        except Exception:
            return ""

    def _send_and_verify(self, editor, *, timeout: float = 2.5) -> None:
        """Post Enter to the bound HWND without a blocking post-send UIA read.

        UIA Invoke/click can activate modern WeChat windows, so it is deliberately
        excluded from this path.
        """
        del timeout
        self._post_enter(editor)
        time.sleep(0.15)

    def _exact_search_results(self, win, chat: str) -> list[Any]:
        wanted = chat.strip()
        if not wanted:
            return []
        matches: list[Any] = []
        seen_controls: set[str] = set()
        try:
            items = win.descendants(control_type="ListItem")
        except Exception:
            return []
        for item in items:
            try:
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
        session_cells = [
            item
            for item in matches
            if "ChatSessionCell" in str(getattr(item.element_info, "class_name", "") or "")
        ]
        return session_cells or matches

    def open_chat(self, chat: str) -> None:
        chat = chat.strip()
        if not chat:
            raise ValueError("chat is required")
        win = self._main_window()
        search = self._search_edit(win)
        try:
            self._set_text(search, chat)
            time.sleep(0.4)
            matches = self._exact_search_results(win, chat)
            if len(matches) > 1:
                self._set_text(search, "")
                raise WeChatUnavailable(
                    f"Ambiguous WeChat search: more than one exact result named {chat!r}"
                )
            if len(matches) == 1:
                # Invoke the exact result itself. Posting Enter to the top-level
                # WeChat HWND is ambiguous when the app is in the background and
                # can leave the previously active conversation selected.
                self._invoke(matches[0])
            else:
                raise WeChatUnavailable(
                    f"No exact background-invokable WeChat result named {chat!r}; foreground fallback is disabled"
                )
            time.sleep(0.35)
        except WeChatUnavailable:
            raise
        except Exception as exc:
            raise WeChatUnavailable(f"Failed to open WeChat conversation {chat!r}: {exc}") from exc
        win = self._main_window()
        if not self._verify_target(win, chat):
            raise WeChatUnavailable(f"Target verification failed after opening conversation: {chat}")

    def _verify_target(self, win, chat: str) -> bool:
        wanted = chat.strip()
        if not wanted:
            return False
        try:
            rect = win.rectangle()
            matches = 0
            for text in win.descendants(control_type="Text"):
                value = self._safe_text(text)
                if value != wanted:
                    continue
                tr = text.rectangle()
                if tr.left >= rect.left + rect.width() // 4 and tr.top <= rect.top + max(220, rect.height() // 3):
                    matches += 1
            return matches == 1
        except Exception:
            return False

    def _is_current_target(self, win, chat: str) -> bool:
        """Verify an already-open compact or main-window conversation."""
        if self._verify_target(win, chat):
            return True
        try:
            return self.current_chat().strip() == chat.strip()
        except Exception:
            return False

    def _message_rows(self, win, chat: str) -> list[dict[str, Any]]:
        rect = win.rectangle()
        rows: list[dict[str, Any]] = []
        seen: set[tuple[int, int, str]] = set()
        try:
            controls = win.descendants(control_type="ListItem")
        except Exception:
            controls = []
        if not controls:
            try:
                controls = win.descendants(control_type="Text")
            except Exception:
                controls = []
        for control in controls:
            try:
                cr = control.rectangle()
                automation_id = str(getattr(control.element_info, "automation_id", "") or "")
                is_chat_bubble = automation_id.startswith("chat_message_list.")
                if not is_chat_bubble and cr.left < rect.left + rect.width() // 3:
                    continue
                if cr.top < rect.top + 100 or cr.bottom > rect.bottom - 80:
                    continue
                labels = [
                    self._safe_text(child)
                    for child in control.descendants(control_type="Text")
                    if self._safe_text(child)
                ]
                text = self._text(control)
                if not text or text == chat:
                    continue
                key = (cr.top, cr.left, text)
                if key in seen:
                    continue
                seen.add(key)
                sender = labels[0] if len(labels) > 1 else None
                body = labels[-1] if labels else text
                timestamp = next((value for value in labels if any(marker in value for marker in self.TIME_MARKERS)), None)
                midpoint = rect.left + (rect.width() * 2 // 3)
                direction = "unknown" if is_chat_bubble else ("outbound" if cr.left >= midpoint else "inbound")
                runtime_id = getattr(control.element_info, "runtime_id", None)
                rows.append({
                    "text": body,
                    "sender": sender if sender != body else None,
                    "time": timestamp,
                    "direction": direction,
                    "message_id": "uia:" + ".".join(str(part) for part in runtime_id) if runtime_id else None,
                    "top": cr.top,
                    "left": cr.left,
                })
            except Exception:
                continue
        rows.sort(key=lambda row: (row["top"], row["left"]))
        return rows

    def current_chat(self) -> str:
        """Identify the already-open conversation without navigating or focusing."""
        win = self._main_window()
        has_editor = False
        for edit in win.descendants(control_type="Edit"):
            try:
                if str(edit.element_info.automation_id or "") == "chat_input_field":
                    has_editor = True
                    break
            except Exception:
                continue
        if not has_editor:
            raise WeChatUnavailable("No WeChat conversation is currently open")

        for control in win.descendants(control_type="Text"):
            try:
                automation_id = str(control.element_info.automation_id or "")
                value = self._safe_text(control)
                if value and automation_id.endswith("current_chat_name_label"):
                    return value
            except Exception:
                continue

        rect = win.rectangle()
        candidates: list[tuple[int, int, str]] = []
        for control in win.descendants(control_type="Text"):
            try:
                value = self._safe_text(control)
                cr = control.rectangle()
                if not value or value.lower() in {"send", "发送"}:
                    continue
                if rect.top + 35 <= cr.top <= rect.top + 145 and cr.left >= rect.left + rect.width() // 5:
                    candidates.append((cr.top, cr.left, value))
            except Exception:
                continue
        if not candidates:
            raise WeChatUnavailable("Could not identify the open WeChat conversation title")
        candidates.sort()
        return candidates[0][2]

    def current_messages(self, limit: int = 20) -> tuple[str, list[dict[str, Any]]]:
        """Read a compact/single-chat window without requiring its chat list."""
        win = self._main_window()
        chat = self.current_chat()
        rows = self._message_rows(win, chat)
        compact = [{
            "text": row["text"],
            "sender": row.get("sender"),
            "time": row.get("time"),
            "direction": row.get("direction"),
            "message_id": row.get("message_id"),
        } for row in rows]
        return chat, compact[-max(1, min(int(limit), 100)) :]

    def get_messages(self, chat: str, limit: int = 20) -> list[dict[str, Any]]:
        win = self._main_window()
        if not self._is_current_target(win, chat):
            self.open_chat(chat)
            win = self._main_window()
        # Fail closed: never parse messages from whatever conversation happened
        # to remain active if navigation did not actually reach the requested one.
        if not self._is_current_target(win, chat):
            raise WeChatUnavailable(
                f"Refusing to read WeChat conversation {chat!r}: target verification failed"
            )
        rows = self._message_rows(win, chat)
        compact: list[dict[str, Any]] = []
        previous_key: tuple[str, str | None, str | None, str] | None = None
        for row in rows:
            key = (row["text"], row.get("sender"), row.get("time"), row.get("direction") or "")
            if key == previous_key:
                continue
            previous_key = key
            compact.append({
                "text": row["text"],
                "sender": row.get("sender"),
                "time": row.get("time"),
                "direction": row.get("direction"),
                "message_id": row.get("message_id"),
            })
        return compact[-max(1, min(int(limit), 100)) :]

    def _message_editor(self, win):
        rect = win.rectangle()
        candidates = []
        for edit in win.descendants(control_type="Edit"):
            try:
                er = edit.rectangle()
                if not edit.is_visible() or not edit.is_enabled():
                    continue
                if er.top >= rect.top + rect.height() // 2:
                    candidates.append((er.width() * er.height(), er.top, edit))
            except Exception:
                continue
        if not candidates:
            raise WeChatUnavailable("Could not locate the WeChat message editor through UI Automation")
        candidates.sort(key=lambda row: (row[0], row[1]), reverse=True)
        return candidates[0][2]

    def _send_button(self, win):
        labels = {"send", "发送"}
        for button in win.descendants(control_type="Button"):
            if self._safe_text(button).strip().lower() in labels:
                return button
        raise WeChatUnavailable(
            "Could not locate a background-invokable WeChat Send button; foreground fallback is disabled"
        )

    def _load_state(self) -> dict[str, Any]:
        try:
            data = json.loads(self._state_path.read_text("utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save_state(self, data: dict[str, Any]) -> None:
        tmp = self._state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
        tmp.replace(self._state_path)

    def send_message(self, chat: str, text: str, *, dry_run: bool = False, duplicate_ttl: int = 600) -> dict[str, Any]:
        chat = chat.strip()
        text = text.strip()
        if not chat or not text:
            raise ValueError("chat and text are required")
        if len(text) > 4000:
            raise ValueError("text exceeds 4000 characters")
        digest = hashlib.sha256(f"{chat}\0{text}".encode("utf-8")).hexdigest()
        with self._lock:
            state = self._load_state()
            previous = state.get(digest)
            now = time.time()
            if isinstance(previous, (int, float)) and now - float(previous) < max(1, duplicate_ttl):
                return {"ok": True, "sent": False, "duplicate_suppressed": True, "chat": chat}
            win = self._main_window()
            if not self._is_current_target(win, chat):
                self.open_chat(chat)
                win = self._main_window()
            if not self._is_current_target(win, chat):
                raise WeChatUnavailable(f"Refusing to send: current conversation is not verified as {chat!r}")
            editor = self._message_editor(win)
            self._set_text(editor, text)
            if dry_run:
                self._set_text(editor, "")
                return {"ok": True, "sent": False, "dry_run": True, "chat": chat, "characters": len(text)}
            if not self._is_current_target(win, chat):
                self._set_text(editor, "")
                raise WeChatUnavailable("Refusing to send because target verification changed")
            self._send_and_verify(editor)
            state[digest] = now
            cutoff = now - max(3600, duplicate_ttl * 4)
            state = {key: value for key, value in state.items() if isinstance(value, (int, float)) and value >= cutoff}
            self._save_state(state)
            return {"ok": True, "sent": True, "chat": chat, "characters": len(text)}
