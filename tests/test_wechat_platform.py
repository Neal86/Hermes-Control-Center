from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "platforms" / "wechat-desktop" / "adapter.py"


def load_platform_module():
    gateway = types.ModuleType("gateway")
    config = types.ModuleType("gateway.config")
    platforms = types.ModuleType("gateway.platforms")
    base = types.ModuleType("gateway.platforms.base")

    class Platform(str):
        pass

    class PlatformConfig:
        def __init__(self, extra=None):
            self.extra = extra or {}

    class BasePlatformAdapter:
        def __init__(self, config, platform):
            self.config = config
            self.platform = platform
            self._running = True

        def _mark_connected(self):
            self._running = True

        def _mark_disconnected(self):
            self._running = False

        async def _send_with_retry(
            self, chat_id, content, reply_to=None, metadata=None, max_retries=2, base_delay=2.0
        ):
            return await self.send(
                chat_id=chat_id, content=content, reply_to=reply_to, metadata=metadata
            )

    class MessageEvent:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class MessageType:
        TEXT = "text"

    class SendResult:
        def __init__(self, success, error=None, message_id=None):
            self.success = success
            self.error = error
            self.message_id = message_id

    config.Platform = Platform
    config.PlatformConfig = PlatformConfig
    base.BasePlatformAdapter = BasePlatformAdapter
    base.MessageEvent = MessageEvent
    base.MessageType = MessageType
    base.SendResult = SendResult

    saved = {
        name: sys.modules.get(name)
        for name in ("gateway", "gateway.config", "gateway.platforms", "gateway.platforms.base")
    }
    sys.modules.update(
        {
            "gateway": gateway,
            "gateway.config": config,
            "gateway.platforms": platforms,
            "gateway.platforms.base": base,
        }
    )
    try:
        name = "hx_wechat_platform_test"
        spec = importlib.util.spec_from_file_location(name, ADAPTER)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        for key, value in saved.items():
            if value is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = value


def test_gateway_file_loader_can_import_hardened_runtime() -> None:
    module = load_platform_module()
    desktop = module.legacy._load_desktop_class()
    assert desktop is module._BoundFactory
    assert not hasattr(module._BoundFactory, "agent")
    assert hasattr(module.BoundWeChatDesktop, "_ui_transaction")


def test_identical_text_with_distinct_ui_ids_is_not_same_inbound_message() -> None:
    module = load_platform_module()
    a = {"message_id": "row-1", "sender": "Alex", "time": "8:00 PM", "text": "?"}
    b = {"message_id": "row-2", "sender": "Alex", "time": "8:00 PM", "text": "?"}
    assert module.WeChatDesktopPlatformAdapter._inbound_fingerprint(
        "Support", a
    ) != module.WeChatDesktopPlatformAdapter._inbound_fingerprint("Support", b)


def test_configured_group_chat_is_routed_as_group() -> None:
    module = load_platform_module()
    adapter = object.__new__(module.WeChatDesktopPlatformAdapter)
    adapter.group_chats = {"Warehouse Support"}
    assert adapter._chat_type("Warehouse Support") == "group"
    assert adapter._chat_type("Alex") == "dm"


def test_unknown_direction_is_not_silently_dropped() -> None:
    module = load_platform_module()
    rows = [
        {"message_id": "1", "text": "hello", "direction": "unknown"},
        {"message_id": "2", "text": "more", "direction": "inbound"},
    ]
    assert [row["message_id"] for row in module.WeChatDesktopPlatformAdapter._trailing_inbound(rows)] == ["1", "2"]


def test_poll_failures_become_degraded_and_back_off() -> None:
    module = load_platform_module()
    adapter = object.__new__(module.WeChatDesktopPlatformAdapter)
    adapter.poll_seconds = 2.0
    adapter._consecutive_failures = 0
    adapter._last_error = None
    adapter._last_success_at = None
    adapter._health = "healthy"
    adapter._write_health = lambda: None
    delays = [adapter._poll_failure(RuntimeError("uia down")) for _ in range(3)]
    assert delays == [2.0, 4.0, 8.0]
    assert adapter._health == "degraded"
    assert adapter._consecutive_failures == 3
    assert adapter._last_error == "uia down"
    adapter._poll_success()
    assert adapter._health == "healthy"
    assert adapter._consecutive_failures == 0


def test_db_adapter_owns_mention_policy_instead_of_legacy_revision() -> None:
    source = ADAPTER.read_text(encoding="utf-8")
    legacy_source = ADAPTER.with_name("adapter_legacy.py").read_text(encoding="utf-8")
    assert "self.require_mention =" in source
    assert "self.mention_name =" in source
    assert "self.require_mention =" in legacy_source
    assert "self.mention_name =" in legacy_source


def test_db_routing_dm_group_and_self_contract() -> None:
    module = load_platform_module()
    adapter = object.__new__(module.WeChatDesktopPlatformAdapter)
    adapter.require_mention = True
    committed = []
    adapter.receiver_state = types.SimpleNamespace(
        commit_db_cursor=lambda conversation_id, sort_seq: committed.append((conversation_id, sort_seq))
    )
    adapter.build_source = lambda **kwargs: kwargs
    delivered = []

    async def handle_message(event):
        delivered.append(event)

    adapter.handle_message = handle_message

    def event(**overrides):
        data = dict(
            account_id="self", conversation_id="neal", conversation_name="Neal",
            conversation_type="dm", sender_id="customer", sender_name="Customer",
            message_id="1", message_type="text", content="你好", is_self=False,
            mentioned_me=False, sort_seq=10, timestamp=module.legacy.datetime.now(module.legacy.UTC),
        )
        data.update(overrides)
        return types.SimpleNamespace(**data)

    # A DM never requires a mention.
    asyncio.run(adapter._deliver_db_event(event()))
    assert len(delivered) == 1
    assert delivered[0].source["chat_type"] == "dm"

    # A group without @mention is acknowledged but never delivered to the Agent.
    asyncio.run(adapter._deliver_db_event(event(
        conversation_id="room@chatroom", conversation_name="Room", conversation_type="group",
        message_id="2", sort_seq=11, mentioned_me=False,
    )))
    assert len(delivered) == 1
    assert ("room@chatroom", 11) in committed

    # Our own outbound message is always dropped before Agent delivery.
    asyncio.run(adapter._deliver_db_event(event(message_id="3", sort_seq=12, is_self=True)))
    assert len(delivered) == 1
    assert ("neal", 12) in committed


def _outbound_test_adapter(module):
    adapter = object.__new__(module.WeChatDesktopPlatformAdapter)
    adapter._db_primary = False
    sent = []

    class Sender:
        def send(self, target, content, *, mention_name=None):
            sent.append((target, content, mention_name))
            wire_text = f"@{mention_name} {content}" if mention_name else content
            return {"fingerprint": "fp", "message_id": "mid", "wire_text": wire_text}

    adapter.sender = Sender()
    adapter.db_receiver = types.SimpleNamespace(conversation_name=lambda chat: chat)
    adapter._recent_outbound = {}
    adapter.receiver_state = types.SimpleNamespace(remember_outbound=lambda *args: None)
    adapter._prune_dedup = lambda now: None
    return adapter, sent


def test_direct_platform_notice_is_suppressed_before_wechat_sender() -> None:
    module = load_platform_module()
    adapter, sent = _outbound_test_adapter(module)
    result = asyncio.run(adapter.send(
        "neal",
        "No home channel is set for Wechat_Desktop. Type /sethome to configure it.",
    ))
    assert result.success is True
    assert sent == []


def test_customer_reply_delivery_path_is_allowed() -> None:
    module = load_platform_module()
    adapter, sent = _outbound_test_adapter(module)
    reply = "这个单号目前没有查到，我帮你再确认一下。"
    result = asyncio.run(adapter._send_with_retry("neal", reply))
    assert result.success is True
    assert sent == [("neal", reply, None)]


def test_group_customer_reply_mentions_current_questioner() -> None:
    module = load_platform_module()
    adapter, sent = _outbound_test_adapter(module)
    reply = "已经查到，我马上发你结果。"
    token = module._GROUP_REPLY_MENTION.set("Mr.Barry")
    try:
        result = asyncio.run(adapter._send_with_retry("room@chatroom", reply))
    finally:
        module._GROUP_REPLY_MENTION.reset(token)
    assert result.success is True
    assert sent == [("room@chatroom", reply, "Mr.Barry")]
