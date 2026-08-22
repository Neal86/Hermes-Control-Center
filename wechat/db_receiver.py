from __future__ import annotations

from typing import Any, Iterable

from .db import BackendUnavailable, detect_backend
from .message_model import WeChatMessageEvent


class DatabaseReceiver:
    """Primary structured WeChat receiver with fail-closed capability detection."""

    def __init__(self, resource: dict[str, Any]) -> None:
        self.resource = dict(resource)
        self.backend = None
        self.last_error: str | None = None

    def connect(self):
        try:
            self.backend = detect_backend(self.resource)
            self.last_error = None
            return self.backend.status()
        except Exception as exc:
            self.backend = None
            self.last_error = str(exc)
            raise BackendUnavailable(str(exc)) from exc

    @property
    def available(self) -> bool:
        return self.backend is not None

    def poll(self, cursors: dict[str, int], mention_names: Iterable[str] = ()) -> tuple[list[WeChatMessageEvent], dict[str, int]]:
        if self.backend is None:
            raise BackendUnavailable(self.last_error or "WeChat DB receiver is not connected")
        return self.backend.new_events(dict(cursors), tuple(mention_names))

    def conversation_name(self, conversation_id: str) -> str:
        if self.backend is None:
            return conversation_id
        return self.backend.conversation_name(conversation_id)

    def verify_outbound(self, conversation_id: str, content: str, *, after_epoch: float, timeout: float = 8.0) -> bool:
        if self.backend is None:
            return False
        return self.backend.verify_outbound(conversation_id, content, after_epoch=after_epoch, timeout=timeout)

    def close(self) -> None:
        backend = self.backend
        self.backend = None
        if backend is not None:
            backend.close()
