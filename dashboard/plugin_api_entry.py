from __future__ import annotations

# Compatibility alias retained for older Control Center installers/doctor checks.
# Hermes v0.20 mounts dashboard/plugin_api.py directly.
from plugin_api import router  # type: ignore

__all__ = ["router"]
