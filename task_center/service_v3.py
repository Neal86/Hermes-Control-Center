from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from task_center.service_v2 import TaskCenter as _TaskCenterV2, _as_dt, _now


class TaskCenter(_TaskCenterV2):
    """v0.4.5 Task Center correctness/performance layer.

    - reads latest Cron execution status with one SQLite connection per profile
      instead of one connection per job;
    - gives every scheduled task a first-occurrence slot before filling the
      remaining upcoming window with recurring expansions.
    """

    def _latest_cron_runs(self, profile: str, job_ids: list[str]) -> dict[str, dict[str, Any]]:
        wanted = [str(job_id) for job_id in dict.fromkeys(job_ids) if str(job_id)]
        if not wanted:
            return {}
        db_path = self._profile_home(profile) / "cron" / "executions.db"
        if not db_path.exists():
            return {}
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        latest: dict[str, dict[str, Any]] = {}
        try:
            if not con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='executions'"
            ).fetchone():
                return {}
            for offset in range(0, len(wanted), 400):
                batch = wanted[offset : offset + 400]
                placeholders = ",".join("?" for _ in batch)
                query = (
                    "SELECT * FROM ("
                    "  SELECT e.*, ROW_NUMBER() OVER ("
                    "    PARTITION BY job_id ORDER BY claimed_at DESC, id DESC"
                    "  ) AS _hx_rank "
                    f"  FROM executions e WHERE job_id IN ({placeholders})"
                    ") WHERE _hx_rank = 1"
                )
                for raw in con.execute(query, batch):
                    row = dict(raw)
                    row.pop("_hx_rank", None)
                    job_id = str(row.get("job_id") or "")
                    if not job_id:
                        continue
                    row["profile"] = profile
                    row["type"] = "cron_run"
                    latest[job_id] = row
            return latest
        finally:
            con.close()

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
        grouped: dict[str, dict[str, Any]] = {
            item["name"]: {**item, "cron": [], "kanban": []} for item in profile_rows
        }
        for item in cron:
            grouped.setdefault(
                item["profile"],
                {"name": item["profile"], "home": "", "cron": [], "kanban": []},
            )["cron"].append(item)
        for item in kanban:
            key = item.get("profile") or "unassigned"
            grouped.setdefault(
                key,
                {"name": key, "home": "", "cron": [], "kanban": []},
            )["kanban"].append(item)
        jobs_by_profile: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for job in cron:
            jobs_by_profile[str(job.get("profile") or "default")].append(job)
        latest_runs: dict[tuple[str, str], dict[str, Any]] = {}
        for profile_name, jobs in jobs_by_profile.items():
            try:
                rows = self._latest_cron_runs(
                    profile_name,
                    [str(job.get("id") or "") for job in jobs],
                )
                for job_id, row in rows.items():
                    latest_runs[(profile_name, job_id)] = row
            except Exception as exc:
                errors.append({"scope": f"cron-history:{profile_name}", "message": str(exc)})
        running_cron = 0
        failed_cron = 0
        failed_statuses = {"failed", "error", "timed_out", "crashed"}
        for job in cron:
            key = (str(job.get("profile") or "default"), str(job.get("id") or ""))
            run = latest_runs.get(key)
            if run and str(run.get("status") or "").lower() in {"claimed", "running"}:
                running_cron += 1
            status = str(job.get("last_status") or (run or {}).get("status") or "").lower()
            if status in failed_statuses:
                failed_cron += 1
        failed_kanban = sum(
            1
            for task in kanban
            if str(task.get("status") or "").lower()
            in {"blocked", "gave_up", "crashed", "timed_out"}
        )
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
    def _sort_key(row: dict[str, Any]) -> tuple[str, str, str]:
        return (
            str(row.get("at") or ""),
            str(row.get("profile") or ""),
            str(row.get("id") or ""),
        )

    def upcoming(
        self,
        hours: int = 168,
        profile: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        now = _now()
        horizon = now + self._bounded_horizon(hours)
        max_items = max(1, min(int(limit), 1000))
        first_rows: list[dict[str, Any]] = []
        recurrence_sources: list[tuple[dict[str, Any], datetime]] = []
        for job in self.cron_jobs(profile):
            next_dt = _as_dt(job.get("next_run_at"))
            if not next_dt or not (now <= next_dt <= horizon) or not job.get("enabled", True):
                continue
            first_rows.append(
                self._upcoming_copy(job, next_dt, recurring=bool(job.get("recurring")))
            )
            if job.get("recurring"):
                recurrence_sources.append((job, next_dt))
        try:
            for task in self.kanban_tasks(profile, include_completed=False):
                dt = _as_dt(task.get("next_run_at"))
                if dt and now <= dt <= horizon:
                    first_rows.append(
                        {
                            "type": "kanban",
                            "id": task["id"],
                            "name": task["name"],
                            "profile": task.get("profile") or "",
                            "at": dt.isoformat(),
                            "schedule": None,
                            "recurring": False,
                        }
                    )
        except Exception:
            pass
        first_rows.sort(key=self._sort_key)
        if len(first_rows) >= max_items:
            return first_rows[:max_items]
        selected = list(first_rows)
        remaining = max_items - len(selected)
        extras: list[dict[str, Any]] = []
        for job, first in recurrence_sources:
            extras.extend(self._expand_recurrence(job, first, horizon, remaining))
        extras.sort(key=self._sort_key)
        selected.extend(extras[:remaining])
        selected.sort(key=self._sort_key)
        return selected[:max_items]

    @staticmethod
    def _bounded_horizon(hours: int) -> timedelta:
        return timedelta(hours=max(1, min(int(hours), 2160)))
