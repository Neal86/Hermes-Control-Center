from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))
from hermes_cli import HermesCLI  # noqa: E402


def _now() -> datetime:
    return datetime.now(UTC)


def _as_dt(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), UTC)
        except Exception:
            return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    except Exception:
        return None


def _iso(value: Any) -> str | None:
    parsed = _as_dt(value)
    if parsed is not None:
        return parsed.isoformat()
    text = str(value or "").strip()
    return text or None


def _schedule_text(schedule: Any, fallback: Any = None) -> str:
    if isinstance(schedule, str):
        return schedule.strip()
    if isinstance(schedule, dict):
        kind = str(schedule.get("kind") or "").lower()
        if kind == "interval":
            try:
                minutes = float(schedule.get("minutes") or 0)
            except (TypeError, ValueError):
                minutes = 0
            if minutes > 0:
                if minutes % 1440 == 0:
                    return f"every {int(minutes / 1440)}d"
                if minutes % 60 == 0:
                    return f"every {int(minutes / 60)}h"
                return f"every {int(minutes) if minutes.is_integer() else minutes}m"
        if kind == "cron" and schedule.get("expr"):
            return str(schedule["expr"]).strip()
        if kind == "once" and schedule.get("run_at"):
            return str(schedule["run_at"]).strip()
        for key in ("display", "expr", "run_at"):
            if schedule.get(key):
                return str(schedule[key]).strip()
    return str(fallback or "").strip()


def _is_recurring_schedule(schedule: Any, fallback: Any = None) -> bool:
    if isinstance(schedule, dict):
        return str(schedule.get("kind") or "").lower() in {"interval", "cron"}
    text = _schedule_text(schedule, fallback).lower()
    return bool(text) and (text.startswith("every ") or len(text.split()) == 5)


class TaskCenter:
    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")).expanduser().resolve()
        self.cli = HermesCLI()
        self.hermes = self.cli.hermes

    def profiles(self) -> list[dict[str, str]]:
        rows = [{"name": "default", "home": str(self.root)}]
        profiles_root = self.root / "profiles"
        if profiles_root.is_dir():
            for path in sorted(profiles_root.iterdir(), key=lambda item: item.name.lower()):
                if path.is_dir() and not path.name.startswith("."):
                    rows.append({"name": path.name, "home": str(path.resolve())})
        return rows

    def _profile_home(self, profile: str | None) -> Path:
        if not profile or profile == "default":
            return self.root
        profiles_root = (self.root / "profiles").resolve()
        path = (profiles_root / profile).resolve()
        if profiles_root not in path.parents or not path.is_dir():
            raise ValueError(f"Unknown Hermes profile: {profile}")
        return path

    def _env_for(self, profile: str | None) -> dict[str, str]:
        return self.cli.profile_env(self._profile_home(profile))

    def _profile_cli(self, profile: str | None, *args: str) -> list[str]:
        return self.cli.profile_command(profile, *args)

    def _cron_jobs(self, profile: str) -> list[dict[str, Any]]:
        path = self._profile_home(profile) / "cron" / "jobs.json"
        if not path.exists():
            return []
        try:
            payload = json.loads(path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        jobs = payload.get("jobs", payload if isinstance(payload, list) else [])
        result: list[dict[str, Any]] = []
        for job in jobs if isinstance(jobs, list) else []:
            if not isinstance(job, dict):
                continue
            row = dict(job)
            raw_schedule = row.get("schedule")
            display = row.get("schedule_display")
            row.update({
                "profile": profile,
                "type": "cron",
                "id": str(row.get("id") or row.get("job_id") or row.get("name") or ""),
            })
            row["name"] = str(row.get("name") or row["id"] or "Untitled cron job")
            row["schedule_raw"] = raw_schedule
            row["schedule"] = _schedule_text(raw_schedule, display)
            row["recurring"] = _is_recurring_schedule(raw_schedule, display)
            row["next_run_at"] = _iso(row.get("next_run_at") or row.get("next_run"))
            row["last_run_at"] = _iso(row.get("last_run_at") or row.get("last_run"))
            row["enabled"] = not bool(row.get("paused")) and row.get("enabled", True) is not False
            result.append(row)
        return result

    def cron_jobs(self, profile: str | None = None) -> list[dict[str, Any]]:
        names = [profile] if profile else [item["name"] for item in self.profiles()]
        rows: list[dict[str, Any]] = []
        for name in names:
            if name:
                rows.extend(self._cron_jobs(name))
        return rows

    def _cron_history(self, profile: str, job_id: str, limit: int) -> list[dict[str, Any]]:
        db_path = self._profile_home(profile) / "cron" / "executions.db"
        if not db_path.exists():
            return []
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        try:
            if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='executions'").fetchone():
                return []
            rows = [dict(row) for row in con.execute(
                "SELECT * FROM executions WHERE job_id=? ORDER BY claimed_at DESC, id DESC LIMIT ?",
                (job_id, max(1, min(int(limit), 200))),
            )]
            for row in rows:
                row["profile"] = profile
                row["type"] = "cron_run"
            return rows
        finally:
            con.close()

    def _kanban(self, args: list[str]) -> Any:
        return self.cli.run_json([self.hermes, "kanban", *args, "--json"])

    def kanban_tasks(self, profile: str | None = None, include_completed: bool = False) -> list[dict[str, Any]]:
        args = ["list"]
        if profile:
            args += ["--assignee", profile]
        if include_completed:
            args.append("--archived")
        payload = self._kanban(args)
        rows = payload.get("tasks", payload) if isinstance(payload, dict) else payload
        result: list[dict[str, Any]] = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            item = dict(row)
            status = str(item.get("status") or "")
            if not include_completed and status in {"done", "completed", "archived", "cancelled"}:
                continue
            item["type"] = "kanban"
            item["profile"] = str(item.get("assignee") or "")
            item["id"] = str(item.get("id") or item.get("task_id") or "")
            item["name"] = str(item.get("title") or item.get("name") or item["id"])
            item["next_run_at"] = _iso(item.get("scheduled_at"))
            result.append(item)
        return result

    def overview(self, profile: str | None = None, include_completed: bool = False) -> dict[str, Any]:
        cron = self.cron_jobs(profile)
        errors: list[dict[str, str]] = []
        try:
            kanban = self.kanban_tasks(profile, include_completed=include_completed)
            kanban_error = None
        except Exception as exc:
            kanban = []
            kanban_error = str(exc)
            errors.append({"scope": "kanban", "message": str(exc)})
        profile_rows = self.profiles()
        if profile:
            profile_rows = [item for item in profile_rows if item["name"] == profile]
        grouped: dict[str, dict[str, Any]] = {item["name"]: {**item, "cron": [], "kanban": []} for item in profile_rows}
        for item in cron:
            grouped.setdefault(item["profile"], {"name": item["profile"], "home": "", "cron": [], "kanban": []})["cron"].append(item)
        for item in kanban:
            key = item.get("profile") or "unassigned"
            grouped.setdefault(key, {"name": key, "home": "", "cron": [], "kanban": []})["kanban"].append(item)
        running_cron = 0
        failed_cron = 0
        for job in cron:
            history = self._cron_history(job["profile"], job["id"], 1)
            if history and history[0].get("status") in {"claimed", "running"}:
                running_cron += 1
            status = str(job.get("last_status") or "").lower()
            if status in {"failed", "error", "timed_out", "crashed"}:
                failed_cron += 1
        failed_kanban = sum(1 for task in kanban if str(task.get("status") or "").lower() in {"blocked", "gave_up", "crashed", "timed_out"})
        return {
            "profiles": list(grouped.values()),
            "counts": {
                "profiles": len(profile_rows),
                "cron": len(cron),
                "recurring": sum(1 for job in cron if job.get("recurring")),
                "one_shot": sum(1 for job in cron if not job.get("recurring")),
                "kanban": len(kanban),
                "running": running_cron + sum(1 for task in kanban if task.get("status") == "running"),
                "failed": failed_cron + failed_kanban,
            },
            "kanban_error": kanban_error,
            "partial": bool(errors),
            "errors": errors,
            "generated_at": _now().isoformat(),
        }

    @staticmethod
    def _upcoming_copy(job: dict[str, Any], at: datetime, *, recurring: bool) -> dict[str, Any]:
        return {"type": "cron", "id": job["id"], "name": job["name"], "profile": job["profile"], "at": at.isoformat(), "schedule": job.get("schedule"), "recurring": recurring}

    def _expand_recurrence(self, job: dict[str, Any], first: datetime, horizon: datetime, remaining: int) -> list[dict[str, Any]]:
        if remaining <= 0 or not job.get("recurring"):
            return []
        raw = job.get("schedule_raw")
        schedule = str(job.get("schedule") or "").strip()
        result: list[dict[str, Any]] = []
        step: timedelta | None = None
        if isinstance(raw, dict) and str(raw.get("kind") or "").lower() == "interval":
            try:
                minutes = float(raw.get("minutes") or 0)
                step = timedelta(minutes=minutes) if minutes > 0 else None
            except (TypeError, ValueError):
                step = None
        elif schedule.lower().startswith("every "):
            interval = schedule[6:].strip().lower()
            try:
                if interval.endswith("m"):
                    step = timedelta(minutes=float(interval[:-1]))
                elif interval.endswith("h"):
                    step = timedelta(hours=float(interval[:-1]))
                elif interval.endswith("d"):
                    step = timedelta(days=float(interval[:-1]))
            except (TypeError, ValueError):
                step = None
        if step is not None and step.total_seconds() > 0:
            cursor = first
            while len(result) < remaining:
                cursor += step
                if cursor > horizon:
                    break
                result.append(self._upcoming_copy(job, cursor, recurring=True))
            return result
        if len(schedule.split()) != 5:
            return []
        try:
            from croniter import croniter
            iterator = croniter(schedule, first)
            while len(result) < remaining:
                cursor = iterator.get_next(datetime)
                if cursor.tzinfo is None:
                    cursor = cursor.replace(tzinfo=UTC)
                cursor = cursor.astimezone(UTC)
                if cursor > horizon:
                    break
                result.append(self._upcoming_copy(job, cursor, recurring=True))
        except Exception:
            return []
        return result

    def upcoming(self, hours: int = 168, profile: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        now = _now()
        horizon = now + timedelta(hours=max(1, min(int(hours), 2160)))
        max_items = max(1, min(int(limit), 1000))
        rows: list[dict[str, Any]] = []
        for job in self.cron_jobs(profile):
            next_dt = _as_dt(job.get("next_run_at"))
            if next_dt and now <= next_dt <= horizon and job.get("enabled", True):
                rows.append(self._upcoming_copy(job, next_dt, recurring=bool(job.get("recurring"))))
                if job.get("recurring"):
                    rows.extend(self._expand_recurrence(job, next_dt, horizon, max_items - len(rows)))
            if len(rows) >= max_items:
                break
        if len(rows) < max_items:
            try:
                for task in self.kanban_tasks(profile, include_completed=False):
                    dt = _as_dt(task.get("next_run_at"))
                    if dt and now <= dt <= horizon:
                        rows.append({"type": "kanban", "id": task["id"], "name": task["name"], "profile": task.get("profile") or "", "at": dt.isoformat(), "schedule": None, "recurring": False})
            except Exception:
                pass
        rows.sort(key=lambda item: item.get("at") or "")
        return rows[:max_items]

    def create(self, args: dict[str, Any]) -> dict[str, Any]:
        task_type = str(args.get("type") or "")
        name = str(args.get("name") or "").strip()
        if not name:
            raise ValueError("name is required")
        if task_type == "cron":
            schedule = str(args.get("schedule") or "").strip()
            prompt = str(args.get("prompt") or "").strip()
            if not schedule or not prompt:
                raise ValueError("cron tasks require schedule and prompt")
            profile = str(args.get("profile") or "").strip() or "default"
            command = self._profile_cli(profile, "cron", "create", schedule, prompt, "--name", name)
            deliver = str(args.get("deliver") or "").strip()
            if deliver:
                command += ["--deliver", deliver]
            return {"ok": True, "type": "cron", "profile": profile, "output": self.cli.run_text(command, env=self._env_for(profile))}
        if task_type == "kanban":
            command = [self.hermes, "kanban", "create", name]
            body = str(args.get("prompt") or "").strip()
            if body:
                command += ["--body", body]
            profile = str(args.get("profile") or "").strip()
            if profile:
                command += ["--assignee", profile]
            if args.get("priority") is not None:
                command += ["--priority", str(int(args["priority"]))]
            return {"ok": True, "type": "kanban", "task": self.cli.run_json([*command, "--json"])}
        raise ValueError("type must be cron or kanban")

    def update(self, args: dict[str, Any]) -> dict[str, Any]:
        task_type = str(args.get("type") or "")
        task_id = str(args.get("id") or "").strip()
        if not task_id:
            raise ValueError("id is required")
        if task_type == "cron":
            profile = str(args.get("profile") or "").strip() or "default"
            command = self._profile_cli(profile, "cron", "edit", task_id)
            supplied = 0
            for field, flag in (("schedule", "--schedule"), ("prompt", "--prompt"), ("name", "--name")):
                if args.get(field) is not None:
                    command += [flag, str(args[field])]
                    supplied += 1
            if supplied == 0:
                raise ValueError("no cron fields supplied")
            return {"ok": True, "type": "cron", "profile": profile, "output": self.cli.run_text(command, env=self._env_for(profile))}
        if task_type == "kanban":
            command = [self.hermes, "kanban", "edit", task_id]
            supplied = 0
            if args.get("name") is not None:
                command += ["--title", str(args["name"])]
                supplied += 1
            if args.get("prompt") is not None:
                command += ["--body", str(args["prompt"])]
                supplied += 1
            if args.get("priority") is not None:
                command += ["--priority", str(int(args["priority"]))]
                supplied += 1
            output = self.cli.run_text(command) if supplied else ""
            profile = str(args.get("profile") or "").strip()
            if profile:
                self.cli.run_text([self.hermes, "kanban", "assign", task_id, profile])
                supplied += 1
            if supplied == 0:
                raise ValueError("no Kanban fields supplied")
            return {"ok": True, "type": "kanban", "output": output}
        raise ValueError("type must be cron or kanban")

    def action(self, args: dict[str, Any]) -> dict[str, Any]:
        task_type = str(args.get("type") or "")
        task_id = str(args.get("id") or "").strip()
        action = str(args.get("action") or "").strip()
        value = str(args.get("value") or "").strip()
        if not task_id or not action:
            raise ValueError("id and action are required")
        if task_type == "cron":
            if action not in {"pause", "resume", "run", "remove"}:
                raise ValueError("unsupported cron action")
            profile = str(args.get("profile") or "").strip() or "default"
            command = self._profile_cli(profile, "cron", action, task_id)
            return {"ok": True, "type": "cron", "profile": profile, "output": self.cli.run_text(command, env=self._env_for(profile))}
        if task_type == "kanban":
            if action == "assign":
                if not value:
                    raise ValueError("assign requires value")
                command = [self.hermes, "kanban", "assign", task_id, value]
            elif action == "archive":
                command = [self.hermes, "kanban", "archive", task_id]
            else:
                raise ValueError("unsupported Kanban action")
            return {"ok": True, "type": "kanban", "output": self.cli.run_text(command)}
        raise ValueError("type must be cron or kanban")

    def history(self, task_type: str, task_id: str, limit: int = 20, profile: str | None = None) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 200))
        if task_type == "cron":
            if profile:
                return self._cron_history(profile, task_id, limit)
            rows: list[dict[str, Any]] = []
            for item in self.profiles():
                rows.extend(self._cron_history(item["name"], task_id, limit))
            rows.sort(key=lambda row: str(row.get("claimed_at") or ""), reverse=True)
            return rows[:limit]
        if task_type == "kanban":
            try:
                payload = self.cli.run_json([self.hermes, "kanban", "runs", task_id, "--json"])
                runs = payload.get("runs", payload) if isinstance(payload, dict) else payload
                if isinstance(runs, list):
                    normalized = []
                    for run in runs[:limit]:
                        if isinstance(run, dict):
                            item = dict(run)
                            item["type"] = "kanban_run"
                            item["task_id"] = task_id
                            normalized.append(item)
                    if normalized:
                        return normalized
            except Exception:
                pass
            matches = [task for task in self.kanban_tasks(include_completed=True) if task["id"] == task_id]
            return matches[:1]
        raise ValueError("type must be cron or kanban")
