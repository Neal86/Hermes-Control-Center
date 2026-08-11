from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from task_center.service import TaskCenter


def write_jobs(home: Path, jobs: list[dict]) -> None:
    path = home / "cron" / "jobs.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"jobs": jobs}), "utf-8")


def write_executions(home: Path, rows: list[tuple]) -> None:
    path = home / "cron" / "executions.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    try:
        con.execute(
            "CREATE TABLE executions (id INTEGER PRIMARY KEY, job_id TEXT, status TEXT, claimed_at TEXT)"
        )
        con.executemany(
            "INSERT INTO executions(id, job_id, status, claimed_at) VALUES (?, ?, ?, ?)", rows
        )
        con.commit()
    finally:
        con.close()


def test_profiles_and_cron_are_aggregated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    support = tmp_path / "profiles" / "support"
    support.mkdir(parents=True)
    write_jobs(tmp_path, [{"id": "d1", "name": "default-job", "schedule": {"kind": "interval", "minutes": 60}, "next_run_at": "2030-01-01T00:00:00Z"}])
    write_jobs(support, [{"id": "s1", "name": "support-job", "schedule": {"kind": "cron", "expr": "0 9 * * *"}, "next_run_at": "2030-01-01T09:00:00Z"}])
    monkeypatch.setattr(TaskCenter, "kanban_tasks", lambda self, profile=None, include_completed=False: [])
    center = TaskCenter(tmp_path)
    overview = center.overview()
    assert [p["name"] for p in overview["profiles"]] == ["default", "support"]
    assert overview["counts"]["cron"] == 2
    assert overview["counts"]["recurring"] == 2
    jobs = center.cron_jobs()
    assert jobs[0]["schedule"] == "every 1h"
    assert jobs[1]["schedule"] == "0 9 * * *"


def test_structured_interval_is_expanded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    start = datetime.now(UTC) + timedelta(minutes=5)
    write_jobs(tmp_path, [{"id": "j1", "name": "check inbox", "schedule": {"kind": "interval", "minutes": 60}, "next_run_at": start.isoformat()}])
    monkeypatch.setattr(TaskCenter, "kanban_tasks", lambda self, profile=None, include_completed=False: [])
    rows = TaskCenter(tmp_path).upcoming(hours=4, limit=20)
    assert len(rows) >= 3
    times = [datetime.fromisoformat(row["at"]) for row in rows]
    assert times == sorted(times)
    assert times[1] - times[0] == timedelta(hours=1)


def test_upcoming_preserves_each_tasks_first_occurrence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime.now(UTC)
    write_jobs(
        tmp_path,
        [
            {
                "id": "fast",
                "name": "every minute",
                "schedule": {"kind": "interval", "minutes": 1},
                "next_run_at": (now + timedelta(minutes=1)).isoformat(),
            },
            {
                "id": "daily",
                "name": "daily report",
                "schedule": {"kind": "interval", "minutes": 1440},
                "next_run_at": (now + timedelta(hours=12)).isoformat(),
            },
        ],
    )
    monkeypatch.setattr(TaskCenter, "kanban_tasks", lambda self, profile=None, include_completed=False: [])
    rows = TaskCenter(tmp_path).upcoming(hours=24, limit=20)
    ids = [row["id"] for row in rows]
    assert "fast" in ids
    assert "daily" in ids
    assert rows == sorted(rows, key=TaskCenter._sort_key)


def test_structured_once_is_not_recurring(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    start = datetime.now(UTC) + timedelta(hours=2)
    write_jobs(tmp_path, [{"id": "j2", "name": "one shot", "schedule": {"kind": "once", "run_at": start.isoformat()}, "next_run_at": start.isoformat()}])
    monkeypatch.setattr(TaskCenter, "kanban_tasks", lambda self, profile=None, include_completed=False: [])
    center = TaskCenter(tmp_path)
    assert center.cron_jobs()[0]["recurring"] is False
    assert center.overview()["counts"]["one_shot"] == 1
    assert len(center.upcoming(hours=4)) == 1


def test_overview_batches_cron_history_per_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime.now(UTC).isoformat()
    write_jobs(
        tmp_path,
        [
            {"id": "a", "name": "a", "schedule": {"kind": "interval", "minutes": 60}, "next_run_at": now},
            {"id": "b", "name": "b", "schedule": {"kind": "interval", "minutes": 60}, "next_run_at": now},
        ],
    )
    write_executions(tmp_path, [(1, "a", "running", now), (2, "b", "completed", now)])
    monkeypatch.setattr(TaskCenter, "kanban_tasks", lambda self, profile=None, include_completed=False: [])
    center = TaskCenter(tmp_path)
    calls = []
    original = center._latest_cron_runs

    def counted(profile, ids):
        calls.append((profile, tuple(ids)))
        return original(profile, ids)

    monkeypatch.setattr(center, "_latest_cron_runs", counted)
    data = center.overview()
    assert len(calls) == 1
    assert set(calls[0][1]) == {"a", "b"}
    assert data["counts"]["running"] == 1


def test_nondefault_cron_create_uses_global_profile_flag(tmp_path: Path) -> None:
    (tmp_path / "profiles" / "support").mkdir(parents=True)
    calls = []
    center = TaskCenter(tmp_path)
    center.hermes = "hermes"
    center.cli.hermes = "hermes"
    center.cli.run_text = lambda command, **kwargs: calls.append((command, kwargs.get("env"))) or "created"
    result = center.create({"type": "cron", "name": "support sweep", "prompt": "Check messages", "schedule": "every 10m", "profile": "support"})
    assert result["profile"] == "support"
    assert calls[0][0][:4] == ["hermes", "-p", "support", "cron"]
    assert "--profile" not in calls[0][0]


def test_nondefault_cron_action_is_profile_scoped(tmp_path: Path) -> None:
    (tmp_path / "profiles" / "support").mkdir(parents=True)
    calls = []
    center = TaskCenter(tmp_path)
    center.hermes = "hermes"
    center.cli.hermes = "hermes"
    center.cli.run_text = lambda command, **kwargs: calls.append(command) or "ok"
    center.action({"type": "cron", "id": "job-1", "action": "pause", "profile": "support"})
    assert calls == [["hermes", "-p", "support", "cron", "pause", "job-1"]]


def test_profile_path_escape_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "profiles").mkdir(parents=True)
    center = TaskCenter(tmp_path)
    with pytest.raises(ValueError):
        center._profile_home("../../outside")


def test_include_completed_requests_archived_kanban(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    center = TaskCenter(tmp_path)
    monkeypatch.setattr(center, "_kanban", lambda args: calls.append(args) or [])
    center.kanban_tasks(include_completed=True)
    assert calls == [["list", "--archived"]]


def test_kanban_history_prefers_native_runs(tmp_path: Path) -> None:
    center = TaskCenter(tmp_path)
    center.hermes = "hermes"
    center.cli.hermes = "hermes"
    calls: list[list[str]] = []

    def fake_json(command, **kwargs):
        calls.append(command)
        return {"runs": [{"id": "r1", "outcome": "completed", "started_at": "2030-01-01T00:00:00Z"}]}

    center.cli.run_json = fake_json
    rows = center.history("kanban", "t1")
    assert calls == [["hermes", "kanban", "runs", "t1", "--json"]]
    assert rows[0]["type"] == "kanban_run"
    assert rows[0]["task_id"] == "t1"


def test_task_overview_reports_partial_kanban_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_jobs(tmp_path, [])
    monkeypatch.setattr(TaskCenter, "kanban_tasks", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("kanban down")))
    data = TaskCenter(tmp_path).overview()
    assert data["partial"] is True
    assert data["errors"][0]["scope"] == "kanban"
