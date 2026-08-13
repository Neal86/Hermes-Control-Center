from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
PLUGIN_ROOT = HERE.parents[2]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from resources.context import current_agent  # noqa: E402
from resources.wechat_bound import BoundWeChatDesktop  # noqa: E402


def _load_legacy():
    path = HERE.with_name("adapter_legacy.py")
    name = "hermes_control_center_wechat_platform_legacy"
    module = sys.modules.get(name)
    if module is not None:
        return module
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load WeChat gateway adapter from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


legacy = _load_legacy()


class _BoundFactory:
    @staticmethod
    def available() -> bool:
        return BoundWeChatDesktop.available()

    def __new__(cls):
        return BoundWeChatDesktop(current_agent())


# The original adapter remains responsible for polling, inbound dedup, Gateway
# MessageEvent routing, automatic Agent replies and exact-target send safety.
# Only its desktop factory is replaced: every gateway process now attaches to
# the WeChat resource explicitly bound to its active Hermes profile/Agent.
legacy._load_desktop_class = lambda: _BoundFactory

WeChatDesktopPlatformAdapter = legacy.WeChatDesktopPlatformAdapter
check_requirements = legacy.check_requirements
validate_config = legacy.validate_config


def register(ctx):
    return legacy.register(ctx)
