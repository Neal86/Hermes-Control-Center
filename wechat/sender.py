from __future__ import annotations

import hashlib
import time
from typing import Any


def outbound_fingerprint(text: str) -> str:
    return hashlib.sha256(str(text or "").strip().encode("utf-8")).hexdigest()


class WeChatSender:
    """Send only to an explicit source chat through the bound runtime."""

    def __init__(self, desktop: Any) -> None:
        self.desktop = desktop

    def send(self, source_chat_id: str, content: str) -> dict[str, Any]:
        chat = str(source_chat_id or "").strip()
        text = str(content or "").strip()
        if not chat:
            raise ValueError("source_chat_id is required")
        if not text:
            raise ValueError("content is required")
        result = self.desktop.send_message(chat, text)
        if not result.get("sent") and not result.get("duplicate_suppressed"):
            raise RuntimeError("WeChat desktop send did not complete")
        fingerprint = outbound_fingerprint(text)
        return {
            "ok": True,
            "chat": chat,
            "fingerprint": fingerprint,
            "message_id": f"wechat-desktop-{fingerprint[:20]}-{int(time.monotonic())}",
            "result": result,
        }
