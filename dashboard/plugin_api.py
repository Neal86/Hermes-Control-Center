from __future__ import annotations

import sys
from pathlib import Path

from fastapi import APIRouter

DASHBOARD_ROOT = Path(__file__).resolve().parent
if str(DASHBOARD_ROOT) not in sys.path:
    sys.path.insert(0, str(DASHBOARD_ROOT))

from plugin_api_v2 import router as v2_router
from extra_api import router as write_router

router = APIRouter()
router.include_router(v2_router)
router.include_router(write_router)
