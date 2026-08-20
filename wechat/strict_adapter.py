from __future__ import annotations

import time
from typing import Any

from .adapter import ChatRow, WeChatDesktop as _BaseWeChatDesktop, WeChatUnavailable


class WeChatDesktop(_BaseWeChatDesktop):
    """Strict background-only WeChat adapter.

    This layer intentionally removes every receive/send path that can resize,
    move, activate, invoke, click, or focus the WeChat window. Receive is a
    read-only UIA tree scan. Reply routing uses UIA SelectionItem only and fails
    closed if the target session is not already exposed by the session list.
    """

    def list_chats(self, limit: int = 50) -> list[ChatRow]:
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
                    "WeChat session list is not exposed in the current layout; strict background mode "
                    "will not resize, restore, move, or activate the window"
                )
            candidates = [
                control
                for control in win.descendants(control_type="ListItem")
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
            unread = any(marker.lower() in lower for marker in self.UNREAD_MARKERS)
            if not unread:
                try:
                    import re
                    unread = bool(re.search(r"[\[【(（]\s*\d+\s*条\s*[\]】)）]", text))
                except Exception:
                    unread = False
            preview_parts = text_children[1:3] if len(text_children) > 1 else own_lines[1:4]
            rows.append(ChatRow(name=name, unread=unread, preview=" ".join(preview_parts)))
            seen.add(name)
            if len(rows) >= max(1, min(int(limit), 200)):
                break
        return rows

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
    def _select_background(control, chat: str) -> None:
        try:
            control.iface_selection_item.Select()
        except Exception as exc:
            raise WeChatUnavailable(
                f"BACKGROUND_SEND_UNSUPPORTED: WeChat session {chat!r} does not expose UIA SelectionItem"
            ) from exc

    def open_chat(self, chat: str) -> None:
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
                "strict background mode will not use search, Invoke, click, keyboard, resize, or foreground fallback"
            )
        self._select_background(matches[0], chat)
        time.sleep(0.2)
        win = self._main_window()
        if not self._is_current_target(win, chat):
            raise WeChatUnavailable(f"Background target verification failed after selecting {chat!r}")

    def status(self) -> dict[str, Any]:
        result = super().status()
        result.update(
            {
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
