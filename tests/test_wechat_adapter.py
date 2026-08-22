from __future__ import annotations

import threading
from pathlib import Path

import pytest

from wechat import WeChatDesktop
from wechat.adapter import WeChatUnavailable


class FakeValuePattern:
    def __init__(self) -> None:
        self.values: list[str] = []

    def SetValue(self, value: str) -> None:
        self.values.append(value)


class FakeEditor:
    def __init__(self) -> None:
        self.iface_value = FakeValuePattern()


def test_status_fails_cleanly_when_not_available(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(WeChatDesktop, "available", staticmethod(lambda: False))
    result = WeChatDesktop(tmp_path).status()
    assert result["available"] is False
    assert result["foreground_fallback"] is False


def test_send_refuses_when_target_cannot_be_verified(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = WeChatDesktop(tmp_path)
    fake_window = object()
    monkeypatch.setattr(client, "open_chat", lambda chat: None)
    monkeypatch.setattr(client, "_main_window", lambda: fake_window)
    monkeypatch.setattr(client, "_is_current_target", lambda win, chat: False)
    with pytest.raises(WeChatUnavailable):
        client.send_message("Customer Group", "hello")


def test_dry_run_writes_and_clears_editor_without_send(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = WeChatDesktop(tmp_path)
    fake_window = object()
    editor = FakeEditor()
    sends: list[bool] = []
    monkeypatch.setattr(client, "_main_window", lambda: fake_window)
    monkeypatch.setattr(client, "_is_current_target", lambda win, chat: True)
    monkeypatch.setattr(client, "_message_editor", lambda win: editor)
    monkeypatch.setattr(client, "_send_and_verify", lambda value: sends.append(True))

    result = client.send_message("Customer Group", "hello", dry_run=True)

    assert result["dry_run"] is True
    assert editor.iface_value.values == ["hello", ""]
    assert sends == []


def test_duplicate_send_is_suppressed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = WeChatDesktop(tmp_path)
    fake_window = object()
    editor = FakeEditor()
    sends: list[bool] = []
    monkeypatch.setattr(client, "_main_window", lambda: fake_window)
    monkeypatch.setattr(client, "_is_current_target", lambda win, chat: True)
    monkeypatch.setattr(client, "_message_editor", lambda win: editor)
    monkeypatch.setattr(client, "_send_and_verify", lambda value: sends.append(True))

    first = client.send_message("Customer Group", "same reply")
    second = client.send_message("Customer Group", "same reply")

    assert first["sent"] is True
    assert second["duplicate_suppressed"] is True
    assert len(sends) == 1


def test_second_instance_times_out_while_ui_transaction_is_held(tmp_path: Path) -> None:
    first = WeChatDesktop(tmp_path, lock_timeout=0.2)
    second = WeChatDesktop(tmp_path, lock_timeout=0.1)
    entered = threading.Event()
    release = threading.Event()

    def hold_lock() -> None:
        with first._ui_transaction():
            entered.set()
            release.wait(timeout=2)

    thread = threading.Thread(target=hold_lock)
    thread.start()
    assert entered.wait(timeout=1)
    try:
        with pytest.raises(WeChatUnavailable, match="Timed out"):
            with second._ui_transaction():
                pass
    finally:
        release.set()
        thread.join(timeout=2)
    assert not thread.is_alive()


def test_message_ids_are_ui_identity_not_screen_coordinates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = WeChatDesktop(tmp_path)
    fake_window = object()
    monkeypatch.setattr(client, "_main_window", lambda: fake_window)
    monkeypatch.setattr(client, "_is_current_target", lambda win, chat: True)

    rows_a = [
        {"text": "?", "sender": "Alex", "time": "8:00 PM", "direction": "inbound", "message_id": "uia:1", "top": 100, "left": 500},
        {"text": "?", "sender": "Alex", "time": "8:00 PM", "direction": "inbound", "message_id": "uia:2", "top": 140, "left": 500},
    ]
    rows_b = [
        {"text": "?", "sender": "Alex", "time": "8:00 PM", "direction": "inbound", "message_id": "uia:1", "top": 220, "left": 700},
        {"text": "?", "sender": "Alex", "time": "8:00 PM", "direction": "inbound", "message_id": "uia:2", "top": 260, "left": 700},
    ]
    monkeypatch.setattr(client, "_message_rows", lambda win, chat: rows_a)
    first = client.get_messages("Support", 10)
    monkeypatch.setattr(client, "_message_rows", lambda win, chat: rows_b)
    second = client.get_messages("Support", 10)

    assert [row["message_id"] for row in first] == ["uia:1", "uia:2"]
    assert [row["message_id"] for row in second] == ["uia:1", "uia:2"]
