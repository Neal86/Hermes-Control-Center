from __future__ import annotations

import ctypes
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class FocusGuard:
    """Audit foreground changes without using them as a navigation mechanism."""

    def __init__(self, *, wechat_hwnd: int, audit_path: Path, metadata: dict[str, Any] | None = None) -> None:
        self.wechat_hwnd = int(wechat_hwnd or 0)
        self.audit_path = audit_path
        self.metadata = dict(metadata or {})

    @staticmethod
    def foreground_hwnd() -> int:
        if os.name != "nt":
            return 0
        try:
            return int(ctypes.windll.user32.GetForegroundWindow() or 0)
        except Exception:
            return 0

    def record(self, *, before: int, after: int, operation: str) -> None:
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "operation": operation,
            "before_hwnd": int(before or 0),
            "after_hwnd": int(after or 0),
            "wechat_hwnd": self.wechat_hwnd,
            **self.metadata,
        }
        try:
            self.audit_path.parent.mkdir(parents=True, exist_ok=True)
            with self.audit_path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def restore_if_stolen(self, *, before: int, operation: str) -> None:
        """Compatibility safety net; never used to choose or navigate a chat."""
        if os.name != "nt" or not before or before == self.wechat_hwnd:
            return
        after = self.foreground_hwnd()
        if after != self.wechat_hwnd:
            return
        self.record(before=before, after=after, operation=operation)
        try:
            ctypes.windll.user32.SetForegroundWindow(int(before))
        except Exception:
            pass
