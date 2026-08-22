from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from wechat.db.account_matcher import match_account
from wechat.db.base import BackendStatus, BackendUnavailable
from wechat.db.schema_probe import probe_sqlite
from wechat.db.backends.wechat4_sqlcipher import _container_text
from wechat.db_receiver import DatabaseReceiver
from wechat.message_model import WeChatMessageEvent
from wechat.state import ReceiverState


def test_message_model_requires_stable_identity() -> None:
    event = WeChatMessageEvent(
        account_id="self", conversation_id="room@chatroom", conversation_name="Room",
        conversation_type="group", sender_id="other", sender_name="Other", message_id="42",
        timestamp=datetime.now(UTC), content="hello", is_self=False, mentioned_me=True, sort_seq=8,
    )
    assert event.conversation_id == "room@chatroom"
    with pytest.raises(ValueError):
        WeChatMessageEvent(
            account_id="", conversation_id="x", conversation_name="x", conversation_type="dm",
            sender_id="x", sender_name="x", message_id="1", timestamp=datetime.now(UTC),
            content="x", is_self=False, mentioned_me=False,
        )


def test_account_matcher_fails_closed_on_ambiguity(tmp_path: Path) -> None:
    first = tmp_path / "wxid_same_a"
    second = tmp_path / "wxid_same_b"
    first.mkdir(); second.mkdir()
    with pytest.raises(BackendUnavailable):
        match_account([first, second], "wxid_same")
    assert match_account([first, second], "wxid_same", verify=lambda path: path == second) == second


def test_schema_probe_detects_capabilities(tmp_path: Path) -> None:
    db = tmp_path / "probe.db"
    with sqlite3.connect(db) as connection:
        connection.execute("create table SessionTable(username text, unread_count integer, last_timestamp integer)")
        connection.execute("create table contact(username text, nick_name text, remark text)")
        connection.execute("create table Msg_deadbeef(server_id integer, sort_seq integer, real_sender_id integer, message_content text)")
    probe = probe_sqlite([db])
    assert {"sessions", "messages", "stable_message_id", "sender_id", "contacts"} <= set(probe.capabilities)


def test_wcdb_container_text_is_recovered_without_replacement_garbage() -> None:
    payload = b"\x28\xb5\x2f\xfd\x00\x00\x00\x00\x00\x00" + "Mr.Barry: \u770b\u770b\u8fd9\u4e2a".encode("utf-8") + b"\x01\x00\x00\x00"
    assert _container_text(payload) == "Mr.Barry: \u770b\u770b\u8fd9\u4e2a"
    assert _container_text(b"\xff\xfe\xfd\xfc") == ""


def test_receiver_state_persists_db_cursors(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    state = ReceiverState("11", path=path)
    state.commit_db_cursor("customer", 20)
    state.commit_db_cursor("customer", 10)
    restored = ReceiverState("11", path=path)
    assert restored.db_cursors == {"customer": 20}


class _FakeBackend:
    def status(self):
        return BackendStatus("fake", "account", "root", "schema", ("messages",))
    def new_events(self, cursors, mention_names=()):
        return [], {"customer": 4}
    def conversation_name(self, conversation_id):
        return {"customer": "Neal"}.get(conversation_id, conversation_id)
    def verify_outbound(self, conversation_id, content, *, after_epoch, timeout=8.0):
        return conversation_id == "customer" and content == "ok"
    def close(self):
        pass


def test_database_receiver_keeps_stable_id_for_send(monkeypatch: pytest.MonkeyPatch) -> None:
    import wechat.db_receiver as module
    monkeypatch.setattr(module, "detect_backend", lambda resource: _FakeBackend())
    receiver = DatabaseReceiver({"hwnd": 1})
    receiver.connect()
    assert receiver.conversation_name("customer") == "Neal"
    assert receiver.verify_outbound("customer", "ok", after_epoch=0) is True
