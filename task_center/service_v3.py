from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from .service_v2 import TaskCenter as _TaskCenterV2, _as_dt, _now


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
                    latest[job_id] = row
            return latest
        finally:
            con.close()

    def overview(self, profile: str | None = None, include_completed: bool = False) -> dict[str, Any]:
        profiles = self._profiles(profile)
        payload = []
        for name in profiles:
            cron_rows = self.list_cron(name)
            latest = self._latest_cron_runs(name, [str(row.get("id") or "") for row in cron_rows])
            for row in cron_rows:
                record = latest.get(str(row.get("id") or ""))
                if record:
                    row["last_run"] = record
                    row["last_status"] = record.get("status") or record.get("state")
                    row["last_error"] = record.get("error")
            kanban_rows = self.list_kanban(name, include_completed=include_completed)
            payload.append({"profile": name, "cron": cron_rows, "kanban": kanban_rows})
        return {"profiles": payload}

    def upcoming(self, hours: int = 168, profile: str | None = None) -> list[dict[str, Any]]:
        horizon = max(1, min(int(hours), 24 * 90))
        start = _now()
        end = start + timedelta(hours=horizon)
        first_occurrence: list[dict[str, Any]] = []
        recurring_tail: list[dict[str, Any]] = []
        for profile_name in self._profiles(profile):
            for row in self.list_cron(profile_name):
                if not row.get("enabled", True):
                    continue
                occurrences = self._cron_occurrences(row, start, end)
                if not occurrences:
                    continue
                first_occurrence.append(self._upcoming_row("cron", profile_name, row, occurrences[0]))
                for when in occurrences[1:]:
                    recurring_tail.append(self._upcoming_row("cron", profile_name, row, when))
            for row in self.list_kanban(profile_name, include_completed=False):
                when = _as_dt(row.get("scheduled_for") or row.get("due_at"))
                if when and start <= when <= end:
                    first_occurrence.append(self._upcoming_row("kanban", profile_name, row, when))

        first_occurrence.sort(key=lambda item: item.get("when") or "")
        recurring_tail.sort(key=lambda item: item.get("when") or "")
        cap = 500
        result = list(first_occurrence[:cap])
        if len(result) < cap:
            result.extend(recurring_tail[: cap - len(result)])
        return result
