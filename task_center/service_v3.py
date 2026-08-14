from __future__ import annotations

import sqlite3
from typing import Any

from .service_v2 import TaskCenter as _TaskCenterV2


class TaskCenter(_TaskCenterV2):
    """Task Center compatibility/performance layer.

    v2 is the canonical public API. Keep the batched Cron execution helper
    available for callers that need it, but delegate overview/upcoming to v2
    so this layer cannot drift when TaskCenter method names evolve.
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
                    if job_id:
                        latest[job_id] = row
            return latest
        finally:
            con.close()

    def overview(self, profile: str | None = None, include_completed: bool = False) -> dict[str, Any]:
        return super().overview(profile=profile, include_completed=include_completed)

    def upcoming(
        self,
        hours: int = 168,
        profile: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        return super().upcoming(hours=hours, profile=profile, limit=limit)
