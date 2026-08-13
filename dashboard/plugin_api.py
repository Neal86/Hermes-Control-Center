from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from fastapi import APIRouter

DASHBOARD_ROOT = Path(__file__).resolve().parent
PLUGIN_ROOT = DASHBOARD_ROOT.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load dashboard API module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return module


core = _load(DASHBOARD_ROOT / "plugin_api_core.py", "hermes_control_center_dashboard_core")
extra = _load(DASHBOARD_ROOT / "extra_api.py", "hermes_control_center_dashboard_extra")
from management import ManagementCenter as RoutedManagementCenter  # noqa: E402
core.ManagementCenter = RoutedManagementCenter

router = APIRouter()
router.include_router(core.router)
router.include_router(extra.router)
