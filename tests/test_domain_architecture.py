from __future__ import annotations

import importlib
from pathlib import Path

from hcc_gateway.routing import build_reply_metadata, source_chat_id
from wechat.identity import compatible_resource, stable_binding_id
from wechat.receiver import group_mentions_me, trailing_inbound
from wechat.state import ReceiverState


def test_hcc_gateway_does_not_shadow_hermes_gateway_namespace() -> None:
    module = importlib.import_module("hcc_gateway")
    assert module.__name__ == "hcc_gateway"
    assert not (Path(__file__).resolve().parents[1] / "gateway").exists()


def test_reply_routing_requires_explicit_source_chat() -> None:
    metadata = build_reply_metadata("Customer A")
    assert source_chat_id(metadata) == "Customer A"


def test_wechat_identity_is_not_pid_or_hwnd_based() -> None:
    assert stable_binding_id("Agent-A") == stable_binding_id("agent-a")
    record = {"hints": {"app": "wechat", "exe": "c:/wechat/wechat.exe", "title": "wechat"}}
    first = {"kind": "wechat", "app": "wechat", "exe": "c:/wechat/wechat.exe", "title": "wechat", "pid": 10, "hwnd": 20}
    second = {"kind": "wechat", "app": "wechat", "exe": "c:/wechat/wechat.exe", "title": "wechat", "pid": 99, "hwnd": 88}
    assert compatible_resource(record, first)
    assert compatible_resource(record, second)


def test_unknown_message_direction_stays_receive_candidate() -> None:
    rows = [
        {"text": "first", "direction": "unknown", "message_id": "1"},
        {"text": "second", "direction": "inbound", "message_id": "2"},
    ]
    assert [row["message_id"] for row in trailing_inbound(rows)] == ["1", "2"]


def test_group_mentions_are_explicit() -> None:
    assert group_mentions_me("[有人@我] Alex: hello")
    assert not group_mentions_me("Alex: hello")


def test_receiver_state_persists_preview_cursor(tmp_path: Path) -> None:
    path = tmp_path / "receiver.json"
    first = ReceiverState("agent-a", path)
    _, _, fingerprint = first.preview_changed("Alex", "hello")
    first.commit_preview("Alex", fingerprint)
    second = ReceiverState("agent-a", path)
    changed, previous, current = second.preview_changed("Alex", "hello")
    assert changed is False
    assert previous == current == fingerprint
