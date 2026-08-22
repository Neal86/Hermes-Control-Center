from __future__ import annotations

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
