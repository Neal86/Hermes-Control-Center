from __future__ import annotations

import hashlib
import json
import os
import platform
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
            import pyperclip  # noqa: F401
        except Exception:
            return False
        return True

    @staticmethod
    def _deps():
        if platform.system() != "Windows":
            raise WeChatUnavailable("wechat-desktop requires native Windows")
        try:
            from pywinauto import Desktop
            from pywinauto.keyboard import send_keys
            import pyperclip
        except Exception as exc:
            raise WeChatUnavailable(
                "Missing Windows dependencies. Install: pip install pywinauto pyperclip"
            ) from exc
        return Desktop, send_keys, pyperclip

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
        try:
            if hasattr(win, "is_minimized") and win.is_minimized():
                win.restore()
                time.sleep(0.15)
        except Exception:
            pass
        try:
            win.set_focus()
        except Exception:
            pass

    def _main_window(self):
        Desktop, _, _ = self._deps()
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
                "reason": "Requires native Windows plus pywinauto and pyperclip",
                "transport": "windows-uia",
                "fail_closed_send": True,
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
            }
        except Exception as exc:
            return {
                "available": False,
                "platform": platform.system(),
                "reason": str(exc),
                "transport": "windows-uia",
                "fail_closed_send": True,
            }

    def list_chats(self, limit: int = 50) -> list[ChatRow]:
        win = self._main_window()
        rows: list[ChatRow] = []
        seen: set[str] = set()
        try:
            candidates = win.descendants(control_type="ListItem")
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
            name = text_children[0] if text_children else self._safe_text(control)
            if not name or name in seen:
                continue
            lower = text.lower()
            unread = any(marker.lower() in lower for marker in self.UNREAD_MARKERS)
            preview = " ".join(text_children[1:3]) if len(text_children) > 1 else ""
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

    def _paste(self, text: str) -> None:
        _, send_keys, pyperclip = self._deps()
        previous = None
        try:
            previous = pyperclip.paste()
        except Exception:
            pass
        pyperclip.copy(text)
        send_keys("^v", pause=0.03)
        if previous is not None:
            time.sleep(0.08)
            try:
                pyperclip.copy(previous)
            except Exception:
                pass

    def _exact_search_results(self, win, chat: str) -> list[Any]:
        wanted = chat.strip()
        if not wanted:
            return []
        matches: list[Any] = []
        seen_handles: set[int] = set()
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
                    labels.insert(0, own)
                if wanted not in labels:
                    continue
                handle = int(getattr(item, "handle", 0) or id(item))
                if handle not in seen_handles:
                    matches.append(item)
                    seen_handles.add(handle)
            except Exception:
                continue
        return matches

    def open_chat(self, chat: str) -> None:
        chat = chat.strip()
        if not chat:
            raise ValueError("chat is required")
        win = self._main_window()
        search = self._search_edit(win)
        try:
            search.click_input()
            _, send_keys, _ = self._deps()
            send_keys("^a{BACKSPACE}", pause=0.03)
            self._paste(chat)
            time.sleep(0.4)
            matches = self._exact_search_results(win, chat)
            if len(matches) > 1:
                send_keys("{ESC}", pause=0.03)
                raise WeChatUnavailable(
                    f"Ambiguous WeChat search: more than one exact result named {chat!r}"
                )
            if len(matches) == 1:
                matches[0].click_input()
            else:
                send_keys("{ENTER}", pause=0.05)
            time.sleep(0.35)
        except WeChatUnavailable:
            raise
        except Exception as exc:
            raise WeChatUnavailable(f"Failed to open WeChat conversation {chat!r}: {exc}") from exc
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
                if cr.left < rect.left + rect.width() // 3:
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
                direction = "outbound" if cr.left >= midpoint else "inbound"
                rows.append({
                    "text": body,
                    "sender": sender if sender != body else None,
                    "time": timestamp,
                    "direction": direction,
                    "top": cr.top,
                    "left": cr.left,
                })
            except Exception:
                continue
        rows.sort(key=lambda row: (row["top"], row["left"]))
        return rows

    def get_messages(self, chat: str, limit: int = 20) -> list[dict[str, Any]]:
        self.open_chat(chat)
        win = self._main_window()
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
            self.open_chat(chat)
            win = self._main_window()
            if not self._verify_target(win, chat):
                raise WeChatUnavailable(f"Refusing to send: current conversation is not verified as {chat!r}")
            editor = self._message_editor(win)
            editor.click_input()
            self._paste(text)
            if dry_run:
                _, send_keys, _ = self._deps()
                send_keys("^a{BACKSPACE}", pause=0.03)
                return {"ok": True, "sent": False, "dry_run": True, "chat": chat, "characters": len(text)}
            if not self._verify_target(win, chat):
                _, send_keys, _ = self._deps()
                send_keys("^a{BACKSPACE}", pause=0.03)
                raise WeChatUnavailable("Refusing to send because target verification changed")
            _, send_keys, _ = self._deps()
            send_keys("{ENTER}", pause=0.05)
            state[digest] = now
            cutoff = now - max(3600, duplicate_ttl * 4)
            state = {key: value for key, value in state.items() if isinstance(value, (int, float)) and value >= cutoff}
            self._save_state(state)
            return {"ok": True, "sent": True, "chat": chat, "characters": len(text)}
