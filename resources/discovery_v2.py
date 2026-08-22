from __future__ import annotations

from typing import Any

from browser.discovery import select_browser_resources
from wechat.discovery import select_wechat_resources

from . import discovery as windows_scan


def discover_resources() -> list[dict[str, Any]]:
    """Coordinate one shared Windows scan into isolated domain discoveries."""
    rows = windows_scan.discover_resources()
    resources = [*select_browser_resources(rows), *select_wechat_resources(rows)]
    return sorted(
        resources,
        key=lambda item: (
            str(item.get("kind") or ""),
            str(item.get("app") or ""),
            str(item.get("title") or "").lower(),
            int(item.get("pid") or 0),
        ),
    )
