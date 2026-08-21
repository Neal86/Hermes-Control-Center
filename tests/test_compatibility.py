from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "compatibility.py"
MODULE_NAME = "hx_compat_test"
spec = importlib.util.spec_from_file_location(MODULE_NAME, PATH)
assert spec and spec.loader
compat = importlib.util.module_from_spec(spec)
sys.modules[MODULE_NAME] = compat
spec.loader.exec_module(compat)


def test_detect_capabilities_handles_missing_project(monkeypatch: pytest.MonkeyPatch) -> None:
    compat.clear_capability_cache()
    monkeypatch.setattr(compat.shutil, "which", lambda value: "C:/Hermes/hermes.exe")

    def fake_run(command, **kwargs):
        name = command[1]
        if name == "project":
            return SimpleNamespace(returncode=2, stdout="", stderr="invalid choice: 'project'")
        return SimpleNamespace(returncode=0, stdout=f"usage: hermes {name}", stderr="")

    monkeypatch.setattr(compat.subprocess, "run", fake_run)
    caps = compat.detect_capabilities(force=True)
    assert caps.hermes is True
    assert caps.profile is True
    assert caps.dashboard is True
    assert caps.project is False
    assert caps.cron is True
    assert caps.kanban is True


def test_capability_probe_is_cached_and_force_refreshes(monkeypatch: pytest.MonkeyPatch) -> None:
    compat.clear_capability_cache()
    monkeypatch.setattr(compat.shutil, "which", lambda value: "C:/Hermes/hermes.exe")
    calls: list[str] = []

    def fake_run(command, **kwargs):
        calls.append(command[1])
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(compat.subprocess, "run", fake_run)
    first = compat.detect_capabilities()
    second = compat.detect_capabilities()
    assert first == second
    assert len(calls) == 6

    compat.detect_capabilities(force=True)
    assert len(calls) == 12


def test_invalid_explicit_binary_is_not_reported_as_hermes(monkeypatch: pytest.MonkeyPatch) -> None:
    compat.clear_capability_cache()
    monkeypatch.setattr(compat.shutil, "which", lambda value: None)
    monkeypatch.setattr(compat.Path, "is_file", lambda self: False)
    caps = compat.detect_capabilities("Z:/missing/hermes.exe", force=True)
    assert caps.hermes is False
    assert caps.plugins is False
    assert caps.project is False


def test_project_unavailable_payload_is_explicit() -> None:
    payload = compat.project_unavailable_payload()
    assert payload["supported"] is False
    assert payload["items"] == []
    assert "hermes project" in payload["message"]
    assert "Agents" in payload["message"]
    assert "restarted or reloaded" in payload["message"]


def test_gateway_start_is_recognized_as_a_windows_spawn_command() -> None:
    cli = compat.HermesCLI("hermes.exe")
    assert cli._is_gateway_spawn_command(["hermes.exe", "-p", "11", "gateway", "start"])
    assert cli._is_gateway_spawn_command(["hermes.exe", "gateway", "restart"])
    assert not cli._is_gateway_spawn_command(["hermes.exe", "-p", "11", "gateway", "status"])
