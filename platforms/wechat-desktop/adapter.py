from __future__ import annotations

import asyncio
import importlib.util
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve()
# User platform plugins are installed flat under ~/.hermes/plugins/<name>.
# The Control Center runtime is the sibling ~/.hermes/plugins/hermes-extensions.
CONTROL_CENTER_ROOT = HERE.parent.parent / "hermes-extensions"
if not CONTROL_CENTER_ROOT.is_dir() and (HERE.parents[2] / "wechat").is_dir():
    # Source checkout: the platform lives below platforms/wechat-desktop
    # while the Control Center package is the repository root.
    CONTROL_CENTER_ROOT = HERE.parents[2]
if not CONTROL_CENTER_ROOT.is_dir():
    raise RuntimeError(f"Hermes Control Center runtime not found at {CONTROL_CENTER_ROOT}")
if str(CONTROL_CENTER_ROOT) not in sys.path:
    sys.path.insert(0, str(CONTROL_CENTER_ROOT))

from resources.bindings import ResourceBindings  # noqa: E402
from resources.context import current_agent, root_hermes_home  # noqa: E402
from resources.wechat_bound import BoundWeChatDesktop  # noqa: E402


def _load_legacy():
    path = HERE.with_name("adapter_legacy.py")
    name = "hermes_control_center_wechat_platform_legacy"
    module = sys.modules.get(name)
    if module is not None:
        return module
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load WeChat gateway adapter from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return module


legacy = _load_legacy()
logger = legacy.logger


class _BoundFactory:
    @staticmethod
    def available() -> bool:
        try:
            agent = current_agent()
            ResourceBindings().require(agent, "wechat", ready=True)
            return bool(BoundWeChatDesktop.available())
        except Exception:
            return False

    def __new__(cls):
        return BoundWeChatDesktop(current_agent())


legacy._load_desktop_class = lambda: _BoundFactory


class WeChatDesktopPlatformAdapter(legacy.WeChatDesktopPlatformAdapter):
    """Two-stage background WeChat receiver with exact source-chat routing.

    Stage 1 watches only session-list previews. A preview change is a candidate,
    not a message decision. Stage 2 background-selects that exact chat through
    UIA SelectionItem, verifies the title, reads real recent message rows, then
    decides DELIVER/SKIP. No foreground fallback, mouse, keyboard, resize or
    window activation is allowed by BoundWeChatDesktop.
    """

    def __init__(self, config):
        super().__init__(config)
        self.allowed_chats = set()
        self._preview_seen: dict[str, str] = {}
        self._baseline_complete = False
        self._health_path = (
            root_hermes_home()
            / "plugin-data"
            / "hermes-extensions"
            / "wechat"
            / "gateway-health.json"
        )
        self._write_health()

    def _allowed(self, chat: str) -> bool:
        del chat
        return True

    @staticmethod
    def _preview_message(preview: str) -> str:
        text = str(preview or "").strip()
        if not text:
            return ""
        return re.sub(r"^\s*(?:(?:上午|下午)\s*)?\d{1,2}:\d{2}\s*", "", text).strip()

    @staticmethod
    def _preview_fingerprint(chat: str, preview: str) -> str:
        raw = f"{chat}\0{preview}".encode("utf-8")
        return legacy.hashlib.sha256(raw).hexdigest()

    @staticmethod
    def _group_mentions_me(text: str) -> bool:
        value = str(text or "").lower()
        return any(
            marker in value
            for marker in (
                "有人@我",
                "[有人@我]",
                "【有人@我】",
                "@我",
                "提到了你",
                "mentioned you",
                "mentioned me",
            )
        )

    @staticmethod
    def _preview_sender(chat_type: str, chat: str, text: str) -> tuple[str, str]:
        if chat_type != "group":
            return chat, text
        for separator in (": ", "："):
            if separator in text:
                sender, body = text.split(separator, 1)
                if sender.strip() and body.strip():
                    return sender.strip(), body.strip()
        return chat, text

    @staticmethod
    def _compact_context(messages: list[dict], limit: int = 12) -> list[dict]:
        compact = []
        for row in messages[-max(1, limit):]:
            compact.append(
                {
                    "text": str(row.get("text") or "").strip(),
                    "sender": str(row.get("sender") or "").strip() or None,
                    "direction": str(row.get("direction") or "").strip().lower() or None,
                    "time": row.get("time"),
                    "message_id": row.get("message_id"),
                }
            )
        return compact

    @staticmethod
    def _trailing_inbound(messages: list[dict]) -> list[dict]:
        """Return the consecutive inbound tail after the most recent outbound row."""
        tail: list[dict] = []
        for row in reversed(messages):
            text = str(row.get("text") or "").strip()
            if not text:
                continue
            direction = str(row.get("direction") or "").strip().lower()
            if direction == "outbound":
                break
            if direction in {"", "inbound"}:
                tail.append(row)
        tail.reverse()
        return tail

    @staticmethod
    def _message_fingerprint(chat: str, rows: list[dict]) -> str:
        parts = [chat]
        for row in rows:
            parts.extend(
                [
                    str(row.get("message_id") or ""),
                    str(row.get("sender") or ""),
                    str(row.get("time") or ""),
                    str(row.get("text") or ""),
                ]
            )
        return legacy.hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()

    def _decision_log(
        self,
        *,
        chat: str,
        preview: str,
        unread: bool,
        decision: str,
        reason: str,
        previous_preview: str | None = None,
        message_count: int | None = None,
        sender: str | None = None,
        mentioned_me: bool | None = None,
    ) -> None:
        logger.info(
            "WECHAT_RECEIVE_DECISION chat=%r preview=%r unread=%s decision=%s reason=%s "
            "previous_preview_fp=%s message_count=%s sender=%r mentioned_me=%s",
            chat,
            preview,
            bool(unread),
            decision,
            reason,
            previous_preview or "-",
            "-" if message_count is None else message_count,
            sender,
            "-" if mentioned_me is None else bool(mentioned_me),
        )

    def _prune_dedup(self, now: float) -> None:
        self._recent_outbound = {
            chat: entry
            for chat, entry in self._recent_outbound.items()
            if now - entry[1] < legacy.OUTBOUND_ECHO_SECONDS * 2
        }
        # Keep actual inbound fingerprints long enough to suppress repeated deep
        # reads while allowing bounded memory use.
        self._seen = {
            chat: entry
            for chat, entry in self._seen.items()
            if now - entry[1] < max(legacy.INBOUND_DEDUP_SECONDS * 10, 1200.0)
        }

    async def _seed_startup_baseline(self) -> None:
        """Create exactly one startup snapshot before the polling task begins."""
        rows = await asyncio.to_thread(self.desktop.list_chats, 200)
        seeded = 0
        for row in rows:
            chat = str(row.name or "").strip()
            preview = self._preview_message(getattr(row, "preview", ""))
            if not chat or not preview:
                continue
            self._preview_seen[chat] = self._preview_fingerprint(chat, preview)
            seeded += 1
            self._decision_log(
                chat=chat,
                preview=preview,
                unread=bool(getattr(row, "unread", False)),
                decision="SKIP",
                reason="startup_baseline",
            )
        self._baseline_complete = True
        logger.info("WECHAT_RECEIVE_BASELINE_COMPLETE chats=%s", seeded)

    async def connect(self, *, is_reconnect: bool = False) -> bool:
        del is_reconnect
        status = await asyncio.to_thread(self.desktop.status)
        if not status.get("available"):
            self._health = "failed"
            self._last_error = str(status.get("reason") or "WeChat desktop unavailable")
            self._write_health()
            return False
        try:
            await self._seed_startup_baseline()
        except Exception as exc:
            self._health = "failed"
            self._last_error = f"startup baseline failed: {exc}"
            self._write_health()
            logger.exception("WeChat startup baseline failed")
            return False
        self._health = "healthy"
        self._last_success_at = legacy.datetime.now(legacy.UTC)
        self._write_health()
        self._mark_connected()
        if self._poll_task is None or self._poll_task.done():
            self._poll_task = asyncio.create_task(self._poll_loop())
        return True

    async def _inspect_candidate(self, row, *, chat: str, preview: str, previous_preview: str | None) -> None:
        """Background-open one changed chat, read real rows, and route or skip."""
        unread = bool(getattr(row, "unread", False))
        preview_mentions_me = self._group_mentions_me(preview)

        # For chats already known to be groups, a preview without WeChat's mention
        # marker can be rejected without changing that WeChat instance's selected chat.
        if chat in self.group_chats and not preview_mentions_me:
            self._preview_seen[chat] = self._preview_fingerprint(chat, preview)
            self._decision_log(
                chat=chat,
                preview=preview,
                unread=unread,
                decision="SKIP",
                reason="group_without_mention",
                previous_preview=previous_preview,
                mentioned_me=False,
            )
            return

        try:
            messages = await asyncio.to_thread(self.desktop.get_messages, chat, 20)
        except Exception:
            # Do not advance preview state: the next poll retries the exact same
            # candidate instead of silently losing it.
            self._decision_log(
                chat=chat,
                preview=preview,
                unread=unread,
                decision="RETRY",
                reason="background_read_failed",
                previous_preview=previous_preview,
                mentioned_me=preview_mentions_me,
            )
            raise

        if not messages:
            self._preview_seen[chat] = self._preview_fingerprint(chat, preview)
            self._decision_log(
                chat=chat,
                preview=preview,
                unread=unread,
                decision="SKIP",
                reason="no_message_rows",
                previous_preview=previous_preview,
                message_count=0,
                mentioned_me=preview_mentions_me,
            )
            return

        latest = messages[-1]
        latest_direction = str(latest.get("direction") or "").strip().lower()
        if latest_direction == "outbound":
            self._preview_seen[chat] = self._preview_fingerprint(chat, preview)
            self._decision_log(
                chat=chat,
                preview=preview,
                unread=unread,
                decision="SKIP",
                reason="actual_latest_outbound",
                previous_preview=previous_preview,
                message_count=len(messages),
                sender=str(latest.get("sender") or "") or None,
                mentioned_me=preview_mentions_me,
            )
            return

        inbound_tail = self._trailing_inbound(messages)
        if not inbound_tail:
            self._preview_seen[chat] = self._preview_fingerprint(chat, preview)
            self._decision_log(
                chat=chat,
                preview=preview,
                unread=unread,
                decision="SKIP",
                reason="no_inbound_tail",
                previous_preview=previous_preview,
                message_count=len(messages),
                mentioned_me=preview_mentions_me,
            )
            return

        sender = str(inbound_tail[-1].get("sender") or chat).strip() or chat
        inferred_group = (
            chat in self.group_chats
            or preview_mentions_me
            or any(
                str(msg.get("sender") or "").strip()
                and str(msg.get("sender") or "").strip() != chat
                for msg in inbound_tail
            )
        )
        if inferred_group:
            self.group_chats.add(chat)
        chat_type = "group" if inferred_group else "dm"

        # Group delivery requires the account-level mention marker from WeChat's
        # session preview. Private chats always deliver when real inbound content
        # changed after the startup baseline.
        if chat_type == "group" and not preview_mentions_me:
            self._preview_seen[chat] = self._preview_fingerprint(chat, preview)
            self._decision_log(
                chat=chat,
                preview=preview,
                unread=unread,
                decision="SKIP",
                reason="group_without_mention",
                previous_preview=previous_preview,
                message_count=len(messages),
                sender=sender,
                mentioned_me=False,
            )
            return

        texts = [str(msg.get("text") or "").strip() for msg in inbound_tail]
        texts = [text for text in texts if text]
        if not texts:
            self._preview_seen[chat] = self._preview_fingerprint(chat, preview)
            return
        text = "\n".join(texts)
        fingerprint = self._message_fingerprint(chat, inbound_tail)
        now = time.monotonic()
        previous_actual = self._seen.get(chat)
        if previous_actual and previous_actual[0] == fingerprint:
            self._preview_seen[chat] = self._preview_fingerprint(chat, preview)
            self._decision_log(
                chat=chat,
                preview=preview,
                unread=unread,
                decision="SKIP",
                reason="duplicate_actual_message",
                previous_preview=previous_preview,
                message_count=len(messages),
                sender=sender,
                mentioned_me=preview_mentions_me,
            )
            return

        outbound_fingerprint = self._outbound_fingerprint(text)
        if self._is_recent(
            self._recent_outbound.get(chat),
            outbound_fingerprint,
            now,
            legacy.OUTBOUND_ECHO_SECONDS,
        ):
            self._seen[chat] = (fingerprint, now)
            self._preview_seen[chat] = self._preview_fingerprint(chat, preview)
            self._decision_log(
                chat=chat,
                preview=preview,
                unread=unread,
                decision="SKIP",
                reason="outbound_echo",
                previous_preview=previous_preview,
                message_count=len(messages),
                sender=sender,
                mentioned_me=preview_mentions_me,
            )
            return

        self._seen[chat] = (fingerprint, now)
        self._preview_seen[chat] = self._preview_fingerprint(chat, preview)
        self._prune_dedup(now)
        source = self.build_source(
            chat_id=chat,
            chat_name=chat,
            chat_type=chat_type,
            user_id=sender,
            user_name=sender,
        )
        event = legacy.MessageEvent(
            text=text,
            message_type=legacy.MessageType.TEXT,
            source=source,
            message_id=f"wechat-desktop-{fingerprint[:20]}-{int(now)}",
            raw_message={
                "chat": chat,
                "source_chat_id": chat,
                "chat_type": chat_type,
                "text": text,
                "sender": sender,
                "mentioned_me": preview_mentions_me,
                "preview": preview,
                "unread": unread,
                "recent_context": self._compact_context(messages, 12),
                "direction": "inbound",
                "transport": "windows-uia-two-stage-background",
                "background_selected_and_verified": True,
                "reply_route": "source_chat_only",
            },
            timestamp=legacy.datetime.now(legacy.UTC),
        )
        self._decision_log(
            chat=chat,
            preview=preview,
            unread=unread,
            decision="DELIVER",
            reason="dm_new_message" if chat_type == "dm" else "group_mentioned_me",
            previous_preview=previous_preview,
            message_count=len(messages),
            sender=sender,
            mentioned_me=preview_mentions_me,
        )
        await self.handle_message(event)

    async def _poll_loop(self) -> None:
        """Watch previews, then deep-read only changed chats in strict background mode."""
        while self._running:
            sleep_for = self.poll_seconds
            try:
                rows = await asyncio.to_thread(self.desktop.list_chats, 200)
                if not self._baseline_complete:
                    # Defensive path only; normal connect seeds the baseline first.
                    await self._seed_startup_baseline()
                    await asyncio.sleep(sleep_for)
                    continue

                for row in rows:
                    chat = str(row.name or "").strip()
                    if not chat:
                        continue
                    preview = self._preview_message(getattr(row, "preview", ""))
                    if not preview:
                        continue
                    preview_fp = self._preview_fingerprint(chat, preview)
                    previous_preview = self._preview_seen.get(chat)
                    if previous_preview == preview_fp:
                        continue

                    reason = "new_chat_after_baseline" if previous_preview is None else "preview_changed_after_baseline"
                    logger.info(
                        "WECHAT_RECEIVE_CANDIDATE chat=%r preview=%r unread=%s reason=%s previous_preview_fp=%s",
                        chat,
                        preview,
                        bool(getattr(row, "unread", False)),
                        reason,
                        previous_preview or "-",
                    )
                    await self._inspect_candidate(
                        row,
                        chat=chat,
                        preview=preview,
                        previous_preview=previous_preview,
                    )

                self._poll_success()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                sleep_for = self._poll_failure(exc)
            await asyncio.sleep(sleep_for)


# legacy.register resolves this global when it creates the adapter factory.
legacy.WeChatDesktopPlatformAdapter = WeChatDesktopPlatformAdapter
check_requirements = legacy.check_requirements
validate_config = legacy.validate_config


def register(ctx):
    # Explicitly opt this local desktop adapter into all senders. This is scoped
    # only to wechat_desktop; it does not open Telegram/Discord/other gateways.
    os.environ["WECHAT_DESKTOP_ALLOW_ALL_USERS"] = "true"
    ctx.register_platform(
        name="wechat_desktop",
        label="WeChat Desktop",
        adapter_factory=lambda cfg: WeChatDesktopPlatformAdapter(cfg),
        check_fn=check_requirements,
        validate_config=validate_config,
        env_enablement_fn=legacy._env_enablement,
        cron_deliver_env_var="WECHAT_DESKTOP_HOME_CHAT",
        allow_all_env="WECHAT_DESKTOP_ALLOW_ALL_USERS",
        max_message_length=4000,
        platform_hint=(
            "This request came from the Agent-bound local Windows WeChat gateway. "
            "The gateway already background-opened and verified the exact source chat and may include "
            "multiple consecutive customer messages as one request. Never use computer_use or any generic "
            "desktop tool to operate WeChat/Weixin. Use bound browser tools when web lookup is needed. "
            "Return only the customer-facing reply; the Gateway delivers it exactly once to source_chat_id."
        ),
        emoji="💬",
    )
