from __future__ import annotations

from typing import Any

from . import discovery as canonical


def discover_resources() -> list[dict[str, Any]]:
    """Backward-compatible alias for the domain-coordinated discovery pass."""
    return canonical.discover_resources()
