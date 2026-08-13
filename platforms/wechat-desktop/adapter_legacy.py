from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import logging
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from gateway.config import Platform, PlatformConfig
from gateway.platforms.base import BasePlatformAdapter, MessageEvent, MessageType, SendResult

logger = logging.getLogger(__name__)

INBOUND_DEDUP_SECONDS = 120.0
OUTBOUND_ECHO_SECONDS = 60.0
MAX_POLL_BACKOFF_SECONDS = 30.0
DEGRADED_AFTER_FAILURES = 3


def _load_desktop_class():
    here = Path(__file__).resolve()
    candidates = [
        here.parents[2] / "wechat" / "runtime.py",
        here.parents[2] / "wechat" / "adapter.py",
        here.parents[2] / "hermes-extensions" / "wechat" / "runtime.py",
        here.parents[2] / "hermes-extensions" / "wechat" / "adapter.py",
    ]
    configured = os.getenv("HERMES_EXTENSIONS_PLUGIN_DIR", "").strip()
    if configured:
        root = Path(configured).expanduser().resolve()
        candidates.insert(0, root / "wechat" / "runtime.py")
        candidates.insert(1, root / "wechat" / "adapter.py")
    path = next((candidate for candidate in candidates if candidate.is_file()), None)
    if path is None:
        raise RuntimeError("Hermes Extensions WeChat automation module is not installed")
    name = "hermes_extensions_wechat_desktop_runtime"
    module = sys.modules.get(name)
    if module is None or Path(getattr(module, "__file__", "")) != path:
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Unable to load WeChat automation module from {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        except Exception:
            sys.modules.pop(name, None)
            raise
    return module.WeChatDesktop


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _csv_set(value: Any) -> set[str]:
    raw = str(value or "")
    return {item.strip() for item in raw.replace("，", ",").split(",") if item.strip()}


def _allowed_chats(config: PlatformConfig) -> set[str]:
    extra = config.extra or {}
    return _csv_set(extra.get("allowed_chats") or os.getenv("WECHAT_DESKTOP_ALLOWED_CHATS", ""))


def _group_chats(config: PlatformConfig) -> set[str]:
    extra = config.extra or {}
    return _csv_set(extra.get("group_chats") or os.getenv("WECHAT_DESKTOP_GROUP_CHATS", ""))


def check_requirements() -> bool:
    try:
        return bool(_load_desktop_class().available())
    except Exception:
        return False


def validate_config(config: PlatformConfig) -> bool:
    del config
    return check_requirements()


def _env_enablement() -> dict[str, Any] | None:
    if not _truthy(os.getenv("WECHAT_DESKTOP_AUTO_ENABLE")):
        return None
    seed: dict[str, Any] = {}
    allowed = os.getenv("WECHAT_DESKTOP_ALLOWED_CHATS", "").strip()
    if allowed:
        seed["allowed_chats"] = allowed
    groups = os.getenv("WECHAT_DESKTOP_GROUP_CHATS", "").strip()
    if groups:
        seed["group_chats"] = groups
    home = os.getenv("WECHAT_DESKTOP_HOME_CHAT", "").strip()
    if home:
        seed["home_channel"] = {"chat_id": home, "name": home}
    return seed


class WeChatDesktopPlatformAdapter(BasePlatformAdapter):
    """Poll unread desktop conversations and route new inbound text into Hermes Gateway."""

    def __init__(self, config: PlatformConfig):
        super().__init__(config=config, platform=Platform("wechat_desktop"))
        desktop = _load_desktop_class()
        self.desktop = desktop()
        self.poll_seconds = max(
            1.0,
            float((config.extra or {}).get("poll_seconds") or os.getenv("WECHAT_DESKTOP_POLL_SECONDS", "2")),
        )
        self.allowed_chats = _allowed_chats(config)
        self.group_chats = _group_chats(config)
        self._poll_task: asyncio.Task | None = None
        self._seen: dict[str, tuple[str, float]] = {}
        self._recent_outbound: dict[str, tuple[str, float]] = {}
        self._consecutive_failures = 0
        self._last_error: str | None = None
        self._last_success_at: datetime | None = None
        self._health = "starting"
        hermes_home = Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")
        self._health_path = (
            hermes_home
            / "plugin-data"
            / "hermes-extensions"
            / "wechat"
            / "gateway-health.json"
        )
        self._write_health()

    def _health_payload(self) -> dict[str, Any]:
        return {
            "status": self._health,
            "consecutive_failures": self._consecutive_failures,
            "last_error": self._last_error,
            "last_success_at": self._last_success_at.isoformat() if self._last_success_at else None,
            "updated_at": datetime.now(UTC).isoformat(),
        }

    def _write_health(self) -> None:
        try:
            self._health_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._health_path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(self._health_payload(), ensure_ascii=False, indent=2),
                "utf-8",
            )
            tmp.replace(self._health_path)
        except Exception:
            pass

    async def connect(self, *, is_reconnect: bool = False) -> bool:
        del is_reconnect
        status = await asyncio.to_thread(self.desktop.status)
        if not status.get("available"):
            self._health = "failed"
            self._last_error = str(status.get("reason") or "WeChat desktop unavailable")
            self._write_health()
            return False
        self._health = "healthy"
        self._last_success_at = datetime.now(UTC)
        self._write_health()
        self._mark_connected()
        if self._poll_task is None or self._poll_task.done():
            self._poll_task = asyncio.create_task(self._poll_loop())
        return True

    async def disconnect(self) -> None:
        self._running = False
        self._health = "stopped"
        self._write_health()
        self._mark_disconnected()
        task = self._poll_task
        self._poll_task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    def health_snapshot(self) -> dict[str, Any]:
        return self._health_payload()

    def _allowed(self, chat: str) -> bool:
        return not self.allowed_chats or chat in self.allowed_chats

    def _chat_type(self, chat: str) -> str:
        return "group" if chat in self.group_chats else "dm"

    @staticmethod
    def _is_recent(entry: tuple[str, float] | None, fingerprint: str, now: float, ttl: float) -> bool:
        return bool(entry and entry[0] == fingerprint and now - entry[1] < ttl)

    @staticmethod
    def _inbound_fingerprint(chat: str, message: dict[str, Any]) -> str:
        message_id = str(message.get("message_id") or "").strip()
        identity = "\0".join(
            [
                chat,
                message_id,
                str(message.get("sender") or ""),
                str(message.get("time") or ""),
                str(message.get("text") or ""),
            ]
        )
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()

    @staticmethod
    def _outbound_fingerprint(text: str) -> str:
        return hashlib.sha256(str(text).strip().encode("utf-8")).hexdigest()

    def _prune_dedup(self, now: float) -> None:
        self._seen = {
            chat: entry
            for chat, entry in self._seen.items()
            if now - entry[1] < INBOUND_DEDUP_SECONDS * 2
        }
        self._recent_outbound = {
            chat: entry
            for chat, entry in self._recent_outbound.items()
            if now - entry[1] < OUTBOUND_ECHO_SECONDS * 2
        }

    def _poll_success(self) -> None:
        if self._consecutive_failures >= DEGRADED_AFTER_FAILURES:
            logger.info(
                "WeChat Desktop polling recovered after %s consecutive failures",
                self._consecutive_failures,
            )
        self._consecutive_failures = 0
        self._last_error = None
        self._last_success_at = datetime.now(UTC)
        self._health = "healthy"
        self._write_health()

    def _poll_failure(self, exc: Exception) -> float:
        self._consecutive_failures += 1
        self._last_error = str(exc)
        self._health = "degraded" if self._consecutive_failures < 10 else "failed"
        self._write_health()
        if self._consecutive_failures == DEGRADED_AFTER_FAILURES or self._consecutive_failures % 10 == 0:
            logger.warning(
                "WeChat Desktop polling failure #%s: %s",
                self._consecutive_failures,
                exc,
            )
        multiplier = 2 ** min(max(self._consecutive_failures - 1, 0), 5)
        return min(MAX_POLL_BACKOFF_SECONDS, self.poll_seconds * multiplier)

    async def _poll_loop(self) -> None:
        while self._running:
            sleep_for = self.poll_seconds
            try:
                unread = await asyncio.to_thread(self.desktop.unread_chats, 200)
                for row in unread:
                    chat = str(row.name or "").strip()
                    if not chat or not self._allowed(chat):
                        continue
                    messages = await asyncio.to_thread(self.desktop.get_messages, chat, 8)
                    if not messages:
                        continue
                    latest = messages[-1]
                    if str(latest.get("direction") or "").lower() == "outbound":
                        continue
                    text = str(latest.get("text") or "").strip()
                    if not text:
                        continue
                    fingerprint = self._inbound_fingerprint(chat, latest)
                    outbound_fingerprint = self._outbound_fingerprint(text)
                    now = time.monotonic()
                    if self._is_recent(self._seen.get(chat), fingerprint, now, INBOUND_DEDUP_SECONDS):
                        continue
                    if self._is_recent(
                        self._recent_outbound.get(chat),
                        outbound_fingerprint,
                        now,
                        OUTBOUND_ECHO_SECONDS,
                    ):
                        self._seen[chat] = (fingerprint, now)
                        continue
                    self._seen[chat] = (fingerprint, now)
                    self._prune_dedup(now)
                    chat_type = self._chat_type(chat)
                    source = self.build_source(
                        chat_id=chat,
                        chat_name=chat,
                        chat_type=chat_type,
                        user_id=str(latest.get("sender") or chat),
                        user_name=str(latest.get("sender") or chat),
                    )
                    event = MessageEvent(
                        text=text,
                        message_type=MessageType.TEXT,
                        source=source,
                        message_id=str(
                            latest.get("message_id")
                            or f"wechat-desktop-{fingerprint[:20]}-{int(now)}"
                        ),
                        raw_message={
                            "chat": chat,
                            "chat_type": chat_type,
                            "text": text,
                            "sender": latest.get("sender"),
                            "display_time": latest.get("time"),
                            "direction": latest.get("direction"),
                            "ui_message_id": latest.get("message_id"),
                            "transport": "windows-uia",
                        },
                        timestamp=datetime.now(UTC),
                    )
                    await self.handle_message(event)
                self._poll_success()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                sleep_for = self._poll_failure(exc)
            await asyncio.sleep(sleep_for)

    async def send(
        self,
        chat_id: str,
        content: str,
        reply_to: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SendResult:
        del reply_to, metadata
        chat = str(chat_id or "").strip()
        if not self._allowed(chat):
            return SendResult(success=False, error=f"WeChat chat is not allow-listed: {chat}")
        try:
            result = await asyncio.to_thread(self.desktop.send_message, chat, content)
        except Exception as exc:
            return SendResult(success=False, error=str(exc))
        if not result.get("sent") and not result.get("duplicate_suppressed"):
            return SendResult(success=False, error="WeChat desktop send did not complete")
        fingerprint = self._outbound_fingerprint(content)
        now = time.monotonic()
        self._recent_outbound[chat] = (fingerprint, now)
        self._prune_dedup(now)
        return SendResult(
            success=True,
            message_id=f"wechat-desktop-{fingerprint[:20]}-{int(now)}",
        )

    async def get_chat_info(self, chat_id: str) -> dict[str, Any]:
        chat = str(chat_id or "").strip()
        return {"name": chat, "type": self._chat_type(chat), "transport": "windows-uia"}


def register(ctx):
    ctx.register_platform(
        name="wechat_desktop",
        label="WeChat Desktop",
        adapter_factory=lambda cfg: WeChatDesktopPlatformAdapter(cfg),
        check_fn=check_requirements,
        validate_config=validate_config,
        env_enablement_fn=_env_enablement,
        cron_deliver_env_var="WECHAT_DESKTOP_HOME_CHAT",
        max_message_length=4000,
        platform_hint=(
            "You are replying through the user's locally logged-in Windows WeChat client. "
            "Use concise plain text. The connector verifies the exact conversation title before every send."
        ),
        emoji="💬",
    )
