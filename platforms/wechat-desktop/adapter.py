from __future__ import annotations

import asyncio
import contextvars
import importlib.util
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve()
CONTROL_CENTER_ROOT = HERE.parent.parent / "hermes-extensions"
if not CONTROL_CENTER_ROOT.is_dir() and (HERE.parents[2] / "wechat").is_dir():
    CONTROL_CENTER_ROOT = HERE.parents[2]
if not CONTROL_CENTER_ROOT.is_dir():
    raise RuntimeError(f"Hermes Control Center runtime not found at {CONTROL_CENTER_ROOT}")
if str(CONTROL_CENTER_ROOT) not in sys.path:
    sys.path.insert(0, str(CONTROL_CENTER_ROOT))

from resources.context import current_agent, root_hermes_home  # noqa: E402
from resources.wechat_bound import BoundWeChatDesktop  # noqa: E402
from wechat.binding import WeChatBindingService  # noqa: E402
from wechat.receiver import (  # noqa: E402
    compact_context,
    group_mentions_me,
    infer_chat_type,
    message_fingerprint,
    normalize_preview,
    trailing_inbound,
)
from wechat.sender import WeChatSender, outbound_fingerprint  # noqa: E402
from wechat.state import ReceiverState  # noqa: E402


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
_BOUND_AGENT: contextvars.ContextVar[str] = contextvars.ContextVar("hcc_wechat_bound_agent", default="default")


class _BoundFactory:
    """Legacy loader target whose Agent selection is context-local, not global."""

    @staticmethod
    def available() -> bool:
        try:
            return bool(BoundWeChatDesktop.available())
        except Exception:
            return False

    def __new__(cls):
        agent = str(_BOUND_AGENT.get() or current_agent()).strip().lower()
        resource = WeChatBindingService().require(agent, ready=True)
        return BoundWeChatDesktop(agent, resource_id=str(resource["id"]))


legacy._load_desktop_class = lambda: _BoundFactory


class WeChatDesktopPlatformAdapter(legacy.WeChatDesktopPlatformAdapter):
    """Thin Hermes Gateway adapter over the WeChat domain modules.

    Receiver parsing/dedup lives in wechat.receiver/state, ownership lives in
    wechat.binding, and outbound delivery lives in wechat.sender. This adapter is
    responsible only for translating those domain results into Hermes events.
    """

    def __init__(self, config):
        self.bound_agent = str((config.extra or {}).get("bound_agent") or current_agent()).strip().lower()
        token = _BOUND_AGENT.set(self.bound_agent)
        try:
            super().__init__(config)
        finally:
            _BOUND_AGENT.reset(token)
        self.allowed_chats = set()
        self.receiver_state = ReceiverState(self.bound_agent)
        self._preview_seen = self.receiver_state.previews
        self._baseline_complete = False
        self.sender = WeChatSender(self.desktop)
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

    _preview_message = staticmethod(normalize_preview)
    _group_mentions_me = staticmethod(group_mentions_me)
    _compact_context = staticmethod(compact_context)
    _trailing_inbound = staticmethod(trailing_inbound)
    _message_fingerprint = staticmethod(message_fingerprint)

    @staticmethod
    def _preview_fingerprint(chat: str, preview: str) -> str:
        return ReceiverState.preview_fingerprint(chat, preview)

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

    def _commit_preview(self, chat: str, preview: str) -> str:
        fingerprint = self._preview_fingerprint(chat, preview)
        self.receiver_state.commit_preview(chat, fingerprint)
        self._preview_seen = self.receiver_state.previews
        return fingerprint

    async def _seed_startup_baseline(self) -> None:
        """Baseline only on first-ever state; preserve cursors across restarts."""
        if self.receiver_state.previews:
            self._baseline_complete = True
            logger.info(
                "WECHAT_RECEIVE_BASELINE_RESTORED agent=%s chats=%s",
                self.bound_agent,
                len(self.receiver_state.previews),
            )
            return

        rows = await asyncio.to_thread(self.desktop.list_chats, 200)
        seeded = 0
        for row in rows:
            chat = str(row.name or "").strip()
            preview = self._preview_message(getattr(row, "preview", ""))
            if not chat or not preview:
                continue
            self._commit_preview(chat, preview)
            seeded += 1
            self._decision_log(
                chat=chat,
                preview=preview,
                unread=bool(getattr(row, "unread", False)),
                decision="SKIP",
                reason="first_install_baseline",
            )
        self._baseline_complete = True
        logger.info("WECHAT_RECEIVE_BASELINE_COMPLETE agent=%s chats=%s", self.bound_agent, seeded)

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
        unread = bool(getattr(row, "unread", False))
        preview_mentions_me = self._group_mentions_me(preview)

        if chat in self.group_chats and not preview_mentions_me:
            self._commit_preview(chat, preview)
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
            self._commit_preview(chat, preview)
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
            self._commit_preview(chat, preview)
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
            self._commit_preview(chat, preview)
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
        chat_type = infer_chat_type(
            chat,
            inbound_tail,
            known_group=chat in self.group_chats,
            mentioned=preview_mentions_me,
        )
        if chat_type == "group":
            self.group_chats.add(chat)
        if chat_type == "group" and not preview_mentions_me:
            self._commit_preview(chat, preview)
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
            self._commit_preview(chat, preview)
            return
        text = "\n".join(texts)
        fingerprint = self._message_fingerprint(chat, inbound_tail)
        now = time.monotonic()
        if self.receiver_state.seen_message(chat, fingerprint):
            self._commit_preview(chat, preview)
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

        echo = outbound_fingerprint(text)
        in_memory_echo = self._is_recent(
            self._recent_outbound.get(chat),
            echo,
            now,
            legacy.OUTBOUND_ECHO_SECONDS,
        )
        persistent_echo = self.receiver_state.recent_outbound(
            chat,
            echo,
            legacy.OUTBOUND_ECHO_SECONDS,
        )
        if in_memory_echo or persistent_echo:
            self.receiver_state.commit_message(chat, fingerprint)
            self._commit_preview(chat, preview)
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
        await self.handle_message(event)
        # Commit only after successful delivery so a failed Gateway handoff is
        # retried rather than silently acknowledged.
        self.receiver_state.commit_message(chat, fingerprint)
        self._commit_preview(chat, preview)
        self._seen[chat] = (fingerprint, now)
        self._prune_dedup(now)
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

    async def _poll_loop(self) -> None:
        while self._running:
            sleep_for = self.poll_seconds
            try:
                rows = await asyncio.to_thread(self.desktop.list_chats, 200)
                if not self._baseline_complete:
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
                    changed, previous_preview, _ = self.receiver_state.preview_changed(chat, preview)
                    if not changed:
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

    async def send(
        self,
        chat_id: str,
        content: str,
        reply_to: str | None = None,
        metadata: dict | None = None,
    ):
        del reply_to, metadata
        chat = str(chat_id or "").strip()
        try:
            result = await asyncio.to_thread(self.sender.send, chat, content)
        except Exception as exc:
            return legacy.SendResult(success=False, error=str(exc))
        now = time.monotonic()
        self._recent_outbound[chat] = (result["fingerprint"], now)
        self.receiver_state.remember_outbound(chat, result["fingerprint"])
        self._prune_dedup(now)
        return legacy.SendResult(success=True, message_id=result["message_id"])


legacy.WeChatDesktopPlatformAdapter = WeChatDesktopPlatformAdapter
check_requirements = legacy.check_requirements


def validate_config(config) -> bool:
    try:
        agent = str((config.extra or {}).get("bound_agent") or current_agent()).strip().lower()
        WeChatBindingService().require(agent, ready=True)
        return check_requirements()
    except Exception as exc:
        logger.error("WeChat Desktop configuration validation failed: %s", exc)
        return False


def register(ctx):
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
            "Never use computer_use or a generic desktop tool to operate WeChat. "
            "Return only the customer-facing reply; the Gateway delivers it exactly once to source_chat_id."
        ),
        emoji="💬",
    )
