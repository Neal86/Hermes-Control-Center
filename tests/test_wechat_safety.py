from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ADAPTER_PATH = ROOT / "wechat" / "adapter.py"
_spec = importlib.util.spec_from_file_location("hx_wechat_safety_test", ADAPTER_PATH)
assert _spec and _spec.loader
adapter_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = adapter_mod
_spec.loader.exec_module(adapter_mod)
WeChatDesktop = adapter_mod.WeChatDesktop
WeChatUnavailable = adapter_mod.WeChatUnavailable

from resources.wechat_bound import BoundWeChatDesktop


class FakeValuePattern:
    def __init__(self) -> None:
        self.values: list[str] = []

    def SetValue(self, value: str) -> None:
        self.values.append(value)


class FakeSearch:
    def __init__(self) -> None:
        self.iface_value = FakeValuePattern()


class FakeResult:
    def __init__(self) -> None:
        self.invoked = 0

    def invoke(self) -> None:
        self.invoked += 1


def test_open_chat_rejects_ambiguous_exact_results(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = WeChatDesktop(tmp_path)
    fake_window = object()
    search = FakeSearch()
    monkeypatch.setattr(client, "_main_window", lambda: fake_window)
    monkeypatch.setattr(client, "_search_edit", lambda win: search)
    monkeypatch.setattr(client, "_exact_search_results", lambda win, chat: [FakeResult(), FakeResult()])

    with pytest.raises(WeChatUnavailable, match="Ambiguous"):
        client.open_chat("Alex")

    assert search.iface_value.values == ["Alex", ""]


def test_open_chat_invokes_single_exact_result_without_keyboard(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = WeChatDesktop(tmp_path)
    fake_window = object()
    search = FakeSearch()
    result = FakeResult()
    monkeypatch.setattr(client, "_main_window", lambda: fake_window)
    monkeypatch.setattr(client, "_search_edit", lambda win: search)
    monkeypatch.setattr(client, "_exact_search_results", lambda win, chat: [result])
    monkeypatch.setattr(client, "_verify_target", lambda win, chat: True)

    client.open_chat("Exact Customer")

    assert search.iface_value.values == ["Exact Customer"]
    assert result.invoked == 1


class FakeElementInfo:
    def __init__(self, automation_id: str) -> None:
        self.automation_id = automation_id


class FakeHeader:
    def __init__(self, value: str) -> None:
        self.element_info = FakeElementInfo("content_view.current_chat_name_label")
        self.value = value

    def window_text(self) -> str:
        return self.value


class FakeBoundWindow:
    def __init__(self, header: str) -> None:
        self.header = FakeHeader(header)

    def descendants(self, control_type=None):
        return [self.header] if control_type == "Text" else []


def test_bound_runtime_header_is_authoritative_over_selected_state(monkeypatch: pytest.MonkeyPatch) -> None:
    client = object.__new__(BoundWeChatDesktop)
    win = FakeBoundWindow("Other Chat")
    monkeypatch.setattr(client, "_session_matches", lambda _win, _chat: [object()])
    monkeypatch.setattr(client, "_session_selected", lambda _control: True)
    assert client._is_current_target(win, "Neal") is False
    win.header.value = "Neal"
    assert client._is_current_target(win, "Neal") is True


def test_open_chat_does_not_trust_stale_selected_state(monkeypatch: pytest.MonkeyPatch) -> None:
    client = object.__new__(BoundWeChatDesktop)
    win = FakeBoundWindow("Other Chat")
    control = object()
    switched: list[str] = []
    monkeypatch.setattr(client, "_main_window", lambda: win)
    monkeypatch.setattr(client, "_session_matches", lambda _win, _chat: [control])
    monkeypatch.setattr(client, "_session_selected", lambda _control: True)
    def switch(_control, *, chat: str) -> None:
        switched.append(chat)
        win.header.value = chat
    monkeypatch.setattr(client, "_select_session_background", switch)
    client.open_chat("Neal")
    assert switched == ["Neal"]
    assert client._current_chat_header(win) == "Neal"


def test_restore_previous_foreground_uses_bound_restore(monkeypatch: pytest.MonkeyPatch) -> None:
    client = object.__new__(BoundWeChatDesktop)
    client.window_handle = 200
    client.resource_id = "wechat:test"
    client.agent = "11"
    restored: list[int] = []
    monkeypatch.setattr(client, "_foreground_hwnd", lambda: 200)
    monkeypatch.setattr(client, "_record_focus_violation", lambda **_kwargs: None)
    monkeypatch.setattr(client, "_restore_bound_foreground", lambda hwnd: restored.append(hwnd) or True)
    client._restore_previous_foreground(before=100, operation="send")
    assert restored == [100]
