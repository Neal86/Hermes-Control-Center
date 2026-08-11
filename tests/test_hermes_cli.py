from __future__ import annotations

import subprocess

import pytest

from hermes_cli import HermesCLI, HermesCLIError


def test_profile_command_scopes_named_profiles() -> None:
    cli = HermesCLI("hermes")
    assert cli.profile_command("default", "cron", "list") == ["hermes", "cron", "list"]
    assert cli.profile_command("support", "cron", "list") == ["hermes", "-p", "support", "cron", "list"]


def test_run_text_raises_structured_error(monkeypatch: pytest.MonkeyPatch) -> None:
    cli = HermesCLI("hermes")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 2, stdout="", stderr="bad command"),
    )
    with pytest.raises(HermesCLIError) as exc:
        cli.run_text(["hermes", "bad"])
    assert exc.value.returncode == 2
    assert "bad command" in str(exc.value)


def test_run_json_rejects_non_json(monkeypatch: pytest.MonkeyPatch) -> None:
    cli = HermesCLI("hermes")
    monkeypatch.setattr(cli, "run_text", lambda *args, **kwargs: "not json")
    with pytest.raises(RuntimeError, match="did not return JSON"):
        cli.run_json(["hermes", "something", "--json"])
