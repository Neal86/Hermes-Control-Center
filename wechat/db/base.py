from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterable

from ..message_model import WeChatMessageEvent


class BackendUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class BackendStatus:
    backend: str
    account_id: str
    data_root: str
    schema_fingerprint: str
    capabilities: tuple[str, ...]


class ReceiverBackend(ABC):
    @abstractmethod
    def status(self) -> BackendStatus: ...

    @abstractmethod
    def bootstrap_cursors(self) -> dict[str, int]: ...

    @abstractmethod
    def unread_events(self, cursors: dict[str, int], mention_names: Iterable[str] = ()) -> tuple[list[WeChatMessageEvent], dict[str, int]]: ...

    @abstractmethod
    def new_events(self, cursors: dict[str, int], mention_names: Iterable[str] = ()) -> tuple[list[WeChatMessageEvent], dict[str, int]]: ...

    @abstractmethod
    def conversation_name(self, conversation_id: str) -> str: ...

    @abstractmethod
    def verify_outbound(self, conversation_id: str, content: str, *, after_epoch: float, timeout: float = 8.0) -> bool: ...

    def close(self) -> None:
        return None
