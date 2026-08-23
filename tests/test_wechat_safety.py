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
