from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class WeChatMessageEvent:
    """Version-independent message fact emitted by a WeChat receiver backend."""

    account_id: str
    conversation_id: str
    conversation_name: str
    conversation_type: str
    sender_id: str
    sender_name: str
    message_id: str
    timestamp: datetime
    content: str
    is_self: bool
    mentioned_me: bool
    message_type: str = "text"
    sort_seq: int = 0
    raw: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.conversation_type not in {"dm", "group"}:
            raise ValueError(f"Unsupported conversation_type: {self.conversation_type}")
        if not self.account_id or not self.conversation_id or not self.message_id:
            raise ValueError("account_id, conversation_id and message_id are required")
        if self.timestamp.tzinfo is None:
            object.__setattr__(self, "timestamp", self.timestamp.replace(tzinfo=UTC))

    @classmethod
    def timestamp_from_epoch(cls, value: int | float | str | None) -> datetime:
        try:
            stamp = float(value or 0)
        except (TypeError, ValueError):
            stamp = 0
        if stamp <= 0:
            return datetime.now(UTC)
        return datetime.fromtimestamp(stamp, tz=UTC)
