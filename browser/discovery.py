from __future__ import annotations

from typing import Any


def select_browser_resources(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Domain filter for browser resources discovered by the shared Windows scan."""
    return [dict(row) for row in rows if str(row.get("kind") or "").strip().lower() == "browser"]
