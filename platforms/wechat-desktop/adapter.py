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
    """Agent-bound WeChat gateway with unrestricted intake and exact source routing."""

    def __init__(self, config):
        super().__init__(config)
        # Chat/user allowlists are deliberately disabled for this local desktop
        # customer-service adapter. Every DM is accepted. Group messages only
        # enter the Agent when WeChat marks the logged-in account as mentioned.
        self.allowed_chats = set()
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

    def _prune_dedup(self, now: float) -> None:
        # Keep one latest inbound fingerprint per chat indefinitely. The listener
        # intentionally does not open unread conversations anymore, so WeChat can
        # leave the unread badge set for hours. This prevents duplicate delivery.
        self._recent_outbound = {
            chat: entry
            for chat, entry in self._recent_outbound.items()
            if now - entry[1] < legacy.OUTBOUND_ECHO_SECONDS * 2
        }

    async def _poll_loop(self) -> None:
        """Poll unread session-list previews without opening chats or stealing focus."""
        while self._running:
            sleep_for = self.poll_seconds
            try:
                unread = await asyncio.to_thread(self.desktop.unread_chats, 200)
                for row in unread:
                    chat = str(row.name or "").strip()
                    if not chat:
                        continue

                    preview = self._preview_message(getattr(row, "preview", ""))
                    if not preview:
                        continue

                    mentioned_me = self._group_mentions_me(preview)
                    # A mention marker is authoritative evidence that this is a
                    # group conversation. Remember it so future ordinary group
                    # messages are ignored even if group_chats was not preconfigured.
                    if mentioned_me:
                        self.group_chats.add(chat)
                    chat_type = self._chat_type(chat)

                    # Every private chat is accepted. Groups are accepted only when
                    # the logged-in customer-service account is explicitly @mentioned.
                    if chat_type == "group" and not mentioned_me:
                        continue

                    sender, text = self._preview_sender(chat_type, chat, preview)
                    if not text:
                        continue

                    latest = {
                        "text": text,
                        "sender": sender,
                        "time": None,
                        "direction": "inbound",
                        "message_id": None,
                    }
                    fingerprint = self._inbound_fingerprint(chat, latest)
                    outbound_fingerprint = self._outbound_fingerprint(text)
                    now = time.monotonic()

                    previous = self._seen.get(chat)
                    if previous and previous[0] == fingerprint:
                        continue
                    if self._is_recent(
                        self._recent_outbound.get(chat),
                        outbound_fingerprint,
                        now,
                        legacy.OUTBOUND_ECHO_SECONDS,
                    ):
                        self._seen[chat] = (fingerprint, now)
                        continue

                    self._seen[chat] = (fingerprint, now)
                    self._prune_dedup(now)
                    source = self.build_source(
                        chat_id=chat,
                        chat_name=chat,
                        chat_type=chat_type,
                        user_id=str(sender or chat),
                        user_name=str(sender or chat),
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
                            "mentioned_me": mentioned_me,
                            "display_time": None,
                            "direction": "inbound",
                            "ui_message_id": None,
                            "transport": "windows-uia-session-preview",
                            "focus_safe_receive": True,
                            "reply_route": "source_chat_only",
                        },
                        timestamp=legacy.datetime.now(legacy.UTC),
                    )
                    await self.handle_message(event)

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
            "Never use computer_use or any generic desktop tool to operate WeChat/Weixin. "
            "Use bound browser tools when web lookup is needed. Return only the customer-facing reply; "
            "the Gateway will deliver it exactly once to the original source chat_id."
        ),
        emoji="💬",
    )
