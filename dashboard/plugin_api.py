from __future__ import annotations

import logging
import sys
from pathlib import Path

DASHBOARD_ROOT = Path(__file__).resolve().parent
if str(DASHBOARD_ROOT) not in sys.path:
    sys.path.insert(0, str(DASHBOARD_ROOT))

logger = logging.getLogger("hermes_control_center.api")

try:
    import plugin_api_v3 as active_api
except Exception:
    logger.exception(
        "Control Center API bootstrap failed: stable_entry=%s active_module=plugin_api_v3.py",
        Path(__file__).resolve(),
    )
    raise

router = active_api.router

logger.info(
    "Control Center API bootstrap: stable_entry=%s active_api=%s route_count=%d",
    Path(__file__).resolve(),
    Path(active_api.__file__).resolve(),
    len(getattr(router, "routes", [])),
)

for route in getattr(router, "routes", []):
    methods = sorted(getattr(route, "methods", None) or [])
    path = getattr(route, "path", "")
    name = getattr(route, "name", "")
    logger.info(
        "Control Center API route: methods=%s path=%s name=%s",
        ",".join(methods) if methods else "-",
        path,
        name,
    )
