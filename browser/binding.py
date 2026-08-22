from __future__ import annotations

from typing import Any

try:  # plugin package import
    from ..resources.bindings import ResourceBindings
except (ImportError, ValueError):  # source/platform import
    from resources.bindings import ResourceBindings


class BrowserBindingService:
    """Browser-specific ownership facade over the shared compatibility store."""

    def __init__(self, bindings: ResourceBindings | None = None) -> None:
        self.bindings = bindings or ResourceBindings()

    def bind(self, resource_id: str, agent: str) -> dict[str, Any]:
        result = self.bindings.bind(resource_id, agent)
        if str(result["resource"].get("kind") or "").strip().lower() != "browser":
            self.bindings.unbind(resource_id)
            raise ValueError("resource is not a browser")
        return result

    def require(self, agent: str, *, ready: bool = True) -> dict[str, Any]:
        return self.bindings.require(agent, "browser", ready=ready)

    def unbind(self, resource_id: str) -> bool:
        return self.bindings.unbind(resource_id)
