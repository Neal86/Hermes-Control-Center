from __future__ import annotations

import logging
import sys
from pathlib import Path

DASHBOARD_ROOT = Path(__file__).resolve().parent
if str(DASHBOARD_ROOT) not in sys.path:
    sys.path.insert(0, str(DASHBOARD_ROOT))

# Use Hermes' native dashboard logger so diagnostics land directly in AGENT.LOG.
logger = logging.getLogger("hermes_cli.web_server")

try:
    import plugin_api_v3 as active_api
except Exception:
    logger.exception(
        "[ControlCenter] API bootstrap failed: stable_entry=%s active_module=plugin_api_v3.py",
        Path(__file__).resolve(),
    )
    raise

# Stable entry contract: Hermes always imports this file, while callers/tests that
# historically imported compatibility models from plugin_api.py keep working.
router = active_api.router
compat = active_api.base.compat
AgentBody = active_api.AgentBody
AgentActionBody = active_api.AgentActionBody
StrictBody = active_api.StrictBody
ManagementCenter = active_api.ManagementCenter
TaskCenter = active_api.TaskCenter

logger.info(
    "[ControlCenter] API bootstrap: stable_entry=%s active_api=%s route_count=%d",
    Path(__file__).resolve(),
    Path(active_api.__file__).resolve(),
    len(getattr(router, "routes", [])),
)

for route in getattr(router, "routes", []):
    methods = sorted(getattr(route, "methods", None) or [])
    path = getattr(route, "path", "")
    name = getattr(route, "name", "")
    logger.info(
        "[ControlCenter] API route: methods=%s path=%s name=%s",
        ",".join(methods) if methods else "-",
        path,
        name,
    )
