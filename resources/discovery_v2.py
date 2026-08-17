from __future__ import annotations

from typing import Any

from . import discovery as legacy


def discover_resources() -> list[dict[str, Any]]:
    """Use the single canonical Windows discovery pass.

    Chrome, Edge, iXBrowser and WeChat are all discovered by discovery.py.
    Keeping one pass avoids a second CIM/EnumWindows scan on every Resources
    refresh, which previously made the dashboard appear hung on Windows.
    """
    return legacy.discover_resources()
