from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from management.service import ManagementCenter, _path_key


def write_profile(home: Path, *, description: str = "", workspace: str = "") -> None:
    home.mkdir(parents=True, exist_ok=True)
    (home / "skills").mkdir(exist_ok=True)
    (home / "cron").mkdir(exist_ok=True)
    (home / "cron" / "jobs.json").write_text(json.dumps({"jobs": []}), "utf-8")
    (home / "profile.yaml").write_text(f"description: {description!r}\n", "utf-8")
    (home / "config.yaml").write_text(
        "model:\n  provider: openrouter\n  default: test/model\nterminal:\n  cwd: " + repr(workspace or ".") + "\n",
        "utf-8",
    )


def center_with_cli(tmp_path: Path, fake) -> ManagementCenter:
    center = ManagementCenter(tmp_path)
    center.hermes = "hermes"
    center.cli.hermes = "hermes"
    center.cli.run_text = fake
    return center


def test_agent_list_reads_native_profile_state(tmp_path: Path) -> None:
    write_profile(tmp_path, description="Root agent", workspace="/repo/root")
    support = tmp_path / "profiles" / "support"
    write_profile(support, description="Support agent", workspace="/repo/support")
    center = center_with_cli(tmp_path, lambda command, **kwargs: "Gateway: running")
    rows = center.agent_list()
    assert [row["name"] for row in rows] == ["default", "support"]
    assert rows[1]["description"] == "Support agent"
    assert rows[1]["workspace"] == "/repo/support"
    assert rows[1]["model"] == "test/model"
    assert rows[1]["gateway"] == "running"


def test_agent_gateway_status_is_probed_directly(tmp_path: Path) -> None:
    write_profile(tmp_path)

    def fake(command, **kwargs):
        if command[-2:] == ["gateway", "status"]:
            return "No gateway process detected\nGateway is not running"
        if command[:4] == ["hermes", "profile", "show", "default"]:
            return "Model: test/model"
        return ""

    center = center_with_cli(tmp_path, fake)
    agent = center.agent_get("default")
    assert agent["gateway"] == "stopped"
    assert agent["status_error"] is None


def test_named_profile_is_running_when_default_gateway_multiplexes(tmp_path: Path) -> None:
    write_profile(tmp_path)
    write_profile(tmp_path / "profiles" / "support")
    (tmp_path / "config.yaml").write_text("gateway:\n  multiplex_profiles: true\n", "utf-8")

    def fake(command, **kwargs):
        if command[-2:] == ["gateway", "status"] and "-p" not in command:
            return "Gateway process running"
        if command[-2:] == ["gateway", "status"]:
            return "Gateway is not running"
        return ""

    center = center_with_cli(tmp_path, fake)
    agent = center.agent_get("support")
    assert agent["gateway"] == "running (multiplexed)"
    assert agent["gateway_managed_by"] == "default"


def test_multiplexed_profile_start_is_already_satisfied(tmp_path: Path) -> None:
    write_profile(tmp_path)
    write_profile(tmp_path / "profiles" / "support")
    (tmp_path / "config.yaml").write_text("gateway:\n  multiplex_profiles: true\n", "utf-8")
    calls: list[list[str]] = []

    def fake(command, **kwargs):
        calls.append(command)
        if command[-2:] == ["gateway", "status"] and "-p" not in command:
            return "Gateway process running"
        return ""

    center = center_with_cli(tmp_path, fake)
    result = center.agent_action("support", "gateway_start")
    assert result["ok"] is True
    assert result["agent"]["gateway"] == "running (multiplexed)"
    assert not any(command[-2:] == ["gateway", "start"] for command in calls)


def test_profile_commands_keep_hermes_home_at_root(tmp_path: Path) -> None:
    write_profile(tmp_path)
    write_profile(tmp_path / "profiles" / "support")
    center = center_with_cli(tmp_path, lambda command, **kwargs: "Gateway: stopped")

    env = center._env_for("support")

    assert Path(env["HERMES_HOME"]) == tmp_path
    assert center._profile_cli("support", "gateway", "status")[-4:] == ["-p", "support", "gateway", "status"]


def test_agent_create_uses_official_profile_and_config_commands(tmp_path: Path) -> None:
    write_profile(tmp_path)
    calls: list[list[str]] = []

    def fake(command, **kwargs):
        calls.append(command)
        if command[:3] == ["hermes", "profile", "create"]:
            write_profile(tmp_path / "profiles" / "support", description="Customer support", workspace=".")
            return "created"
        if command[:4] == ["hermes", "profile", "show", "support"]:
            return "Gateway: stopped"
        return "ok"

    center = center_with_cli(tmp_path, fake)
    center.agent_create({
        "name": "support",
        "description": "Customer support",
        "clone_mode": "clone",
        "clone_from": "default",
        "workspace": "/work/support",
        "provider": "openrouter",
        "model": "openrouter/test-model",
    })
    assert calls[0] == ["hermes", "profile", "create", "support", "--clone", "--clone-from", "default", "--description", "Customer support"]
    assert ["hermes", "-p", "support", "config", "set", "terminal.cwd", "/work/support"] in calls
    assert ["hermes", "-p", "support", "config", "set", "model.provider", "openrouter"] in calls
    assert ["hermes", "-p", "support", "config", "set", "model.default", "openrouter/test-model"] in calls


def test_create_failure_does_not_apply_post_create_config(tmp_path: Path) -> None:
    write_profile(tmp_path)
    calls: list[list[str]] = []

    def fake(command, **kwargs):
        calls.append(command)
        if command[:3] == ["hermes", "profile", "create"]:
            raise RuntimeError("create failed")
        return "ok"

    center = center_with_cli(tmp_path, fake)
    with pytest.raises(RuntimeError, match="create failed"):
        center.agent_create({"name": "support", "workspace": "/work/support"})
    assert len(calls) == 1


def test_agent_rename_returns_new_profile(tmp_path: Path) -> None:
    write_profile(tmp_path)
    old = tmp_path / "profiles" / "old"
    write_profile(old, description="Old")

    def fake(command, **kwargs):
        if command[:4] == ["hermes", "profile", "rename", "old"]:
            old.rename(tmp_path / "profiles" / "new")
            return "renamed"
        if command[:4] == ["hermes", "profile", "show", "new"]:
            return "Gateway: stopped"
        return "ok"

    center = center_with_cli(tmp_path, fake)
    result = center.agent_update("old", {"name": "new"})
    assert result["agent"]["name"] == "new"


def test_agent_delete_protects_default_and_active(tmp_path: Path) -> None:
    write_profile(tmp_path)
    support = tmp_path / "profiles" / "support"
    write_profile(support)
    center = ManagementCenter(tmp_path)
    with pytest.raises(ValueError, match="default profile"):
        center.agent_delete("default")
    (tmp_path / "active_profile").write_text("support", "utf-8")
    with pytest.raises(ValueError, match="active/default-selected"):
        center.agent_delete("support")


def test_soul_write_is_profile_scoped_and_atomic(tmp_path: Path) -> None:
    write_profile(tmp_path)
    support = tmp_path / "profiles" / "support"
    write_profile(support)
    center = center_with_cli(tmp_path, lambda command, **kwargs: "Gateway: stopped")
    center.agent_update("support", {"soul": "You are support."})
    assert (support / "SOUL.md").read_text("utf-8") == "You are support."
    with pytest.raises(ValueError):
        center.agent_update("../../outside", {"soul": "bad"})


def test_soul_update_invalidates_live_session_prompts_but_preserves_history(tmp_path: Path) -> None:
    import sqlite3

    write_profile(tmp_path)
    with sqlite3.connect(tmp_path / "state.db") as db:
        db.execute(
            "CREATE TABLE sessions (id TEXT PRIMARY KEY, ended_at REAL, system_prompt TEXT, system_prompt_hash TEXT)"
        )
        db.execute("INSERT INTO sessions VALUES ('live', NULL, 'old prompt', 'old-hash')")
        db.execute("INSERT INTO sessions VALUES ('ended', 1.0, 'historical prompt', 'historical-hash')")

    center = center_with_cli(tmp_path, lambda command, **kwargs: "Gateway: stopped")
    result = center.agent_update("default", {"soul": "New SOUL"})

    assert result["session_prompts_invalidated"] == 1
    with sqlite3.connect(tmp_path / "state.db") as conn:
        live = conn.execute(
            "SELECT system_prompt, system_prompt_hash FROM sessions WHERE id='live'"
        ).fetchone()
        ended = conn.execute(
            "SELECT system_prompt, system_prompt_hash FROM sessions WHERE id='ended'"
        ).fetchone()
    assert live == (None, None)
    assert ended == ("historical prompt", "historical-hash")
    assert (tmp_path / "SOUL.md").read_text("utf-8") == "New SOUL"


def test_gateway_transition_must_be_verified(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_profile(tmp_path)
    calls: list[list[str]] = []

    def fake(command, **kwargs):
        calls.append(command)
        if command[-2:] == ["gateway", "start"]:
            return "start requested"
        if command[-2:] == ["gateway", "status"]:
            return "Gateway: stopped"
        if command[:4] == ["hermes", "profile", "show", "default"]:
            return "Gateway: stopped"
        return "ok"

    center = center_with_cli(tmp_path, fake)
    monkeypatch.setattr("management.service.time.sleep", lambda _: None)
    monkeypatch.setattr("management.service.time.monotonic", iter([0.0, 0.0, 20.0]).__next__)
    result = center.agent_action("default", "gateway_start")
    assert result["ok"] is False
    assert "could not be verified" in result["warning"]


def test_path_normalization_matches_equivalent_workspace(tmp_path: Path) -> None:
    folder = tmp_path / "Repo"
    folder.mkdir()
    same = folder / ".." / "Repo"
    assert _path_key(folder) == _path_key(same)
    if os.name == "nt":
        assert _path_key(str(folder).upper()) == _path_key(str(folder).lower())


def test_project_list_and_show_parsing() -> None:
    list_text = "* warehouse                Warehouse Ops  [2 folder(s)]\n  old-project              Old Project (archived)  [1 folder(s)]"
    rows = ManagementCenter._parse_project_list(list_text, "default")
    assert rows[0]["active"] is True
    assert rows[0]["slug"] == "warehouse"
    assert rows[1]["archived"] is True
    show = ManagementCenter._parse_project_show(
        "warehouse  [abc123]\n  name:    Warehouse Ops\n  board:   warehouse\n  primary: /repo/main\n  folders:\n    * /repo/main\n      /repo/docs (Docs)",
        "default",
    )
    assert show["primary_path"] == "/repo/main"
    assert show["folders"][0]["is_primary"] is True
    assert show["folders"][1]["label"] == "Docs"


def test_project_create_uses_native_cli_and_assigns_workspace_agent(tmp_path: Path) -> None:
    write_profile(tmp_path, workspace=".")
    write_profile(tmp_path / "profiles" / "support", workspace=".")
    calls: list[list[str]] = []

    def fake(command, **kwargs):
        calls.append(command)
        if "create" in command and "project" in command:
            return "Created project warehouse (abc123)"
        if "show" in command and "project" in command:
            return "warehouse  [abc123]\n  name:    Warehouse\n  primary: /repo/warehouse\n  folders:\n    * /repo/warehouse"
        if command[:4] in (["hermes", "profile", "show", "default"], ["hermes", "profile", "show", "support"]):
            return "Gateway: stopped"
        return "ok"

    center = center_with_cli(tmp_path, fake)
    result = center.project_create({"name": "Warehouse", "primary": "/repo/warehouse", "profile": "default", "agent": "support", "use": True})
    assert result["project"]["slug"] == "warehouse"
    assert ["hermes", "project", "create", "Warehouse", "--primary", "/repo/warehouse", "--use"] in calls
    assert ["hermes", "-p", "support", "config", "set", "terminal.cwd", "/repo/warehouse"] in calls


def test_project_update_rejects_fake_editable_fields(tmp_path: Path) -> None:
    write_profile(tmp_path)

    def fake(command, **kwargs):
        if "show" in command and "project" in command:
            return "ops  [id1]\n  name:    Ops\n  primary: /repo/ops\n  folders:\n    * /repo/ops"
        return "ok"

    center = center_with_cli(tmp_path, fake)
    with pytest.raises(ValueError, match="does not currently expose editing"):
        center.project_update("ops", "default", {"description": "new"})


def test_snapshot_avoids_project_agent_n_squared_runtime_probes(tmp_path: Path) -> None:
    write_profile(tmp_path, workspace="/repo/root")
    write_profile(tmp_path / "profiles" / "support", workspace="/repo/support")
    calls: list[list[str]] = []

    def fake(command, **kwargs):
        calls.append(command)
        if command[:3] == ["hermes", "profile", "show"]:
            return "Gateway: running"
        if command[-2:] == ["project", "list"] or command[-3:] == ["project", "list", "--all"]:
            return "* root  Root  [1 folder(s)]" if "-p" not in command else "* support  Support  [1 folder(s)]"
        if "project" in command and "show" in command:
            if "-p" in command:
                return "support  [id2]\n  name: Support\n  primary: /repo/support\n  folders:\n    * /repo/support"
            return "root  [id1]\n  name: Root\n  primary: /repo/root\n  folders:\n    * /repo/root"
        return "ok"

    center = center_with_cli(tmp_path, fake)
    data = center.snapshot()
    profile_show_calls = [c for c in calls if c[:3] == ["hermes", "profile", "show"]]
    assert len(profile_show_calls) == 2
    assert len(data["projects"]) == 2


def test_snapshot_reports_partial_profile_errors(tmp_path: Path) -> None:
    write_profile(tmp_path)
    write_profile(tmp_path / "profiles" / "broken")

    def fake(command, **kwargs):
        if command[:3] == ["hermes", "profile", "show"]:
            return "Gateway: stopped"
        if "-p" in command and "broken" in command and "project" in command:
            raise RuntimeError("project DB unavailable")
        if "project" in command and "list" in command:
            return "No projects yet."
        return "ok"

    center = center_with_cli(tmp_path, fake)
    data = center.snapshot()
    assert data["partial"] is True
    assert any(row["scope"] == "projects:broken" for row in data["errors"])

def test_dashboard_soul_update_refreshes_running_gateway_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import sqlite3

    write_profile(tmp_path)
    with sqlite3.connect(tmp_path / "state.db") as db:
        db.execute(
            "CREATE TABLE sessions (id TEXT PRIMARY KEY, ended_at REAL, system_prompt TEXT, system_prompt_hash TEXT)"
        )
        db.execute("INSERT INTO sessions VALUES ('live', NULL, 'old prompt', 'old-hash')")
    center = center_with_cli(tmp_path, lambda command, **kwargs: "Gateway: running")
    monkeypatch.setattr(center, "_normalized_gateway_state", lambda profile: "running")
    calls = []

    def fake_action(profile, action, value=None):
        calls.append((profile, action))
        return {"ok": True, "action": action, "gateway_state": "running"}

    monkeypatch.setattr(center, "agent_action", fake_action)
    result = center.agent_update("default", {"soul": "new"}, refresh_runtime=True)
    assert calls == [("default", "gateway_restart")]
    assert result["runtime_refreshed"] is True


def test_autonomous_soul_update_does_not_restart_its_own_gateway(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_profile(tmp_path)
    center = center_with_cli(tmp_path, lambda command, **kwargs: "Gateway: running")
    monkeypatch.setattr(center, "_normalized_gateway_state", lambda profile: "running")
    monkeypatch.setattr(center, "agent_action", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not restart")))
    result = center.agent_update("default", {"soul": "new"})
    assert result["runtime_refreshed"] is False
