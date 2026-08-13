from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REQUIRED_ROUTES = {
    "/management/overview",
    "/agents",
    "/projects",
    "/tasks",
    "/providers",
    "/resources",
}


def main() -> int:
    dashboard_root = Path(__file__).resolve().parent
    plugin_root = dashboard_root.parent
    if str(plugin_root) not in sys.path:
        sys.path.insert(0, str(plugin_root))

    api_path = dashboard_root / "plugin_api.py"
    spec = importlib.util.spec_from_file_location("hermes_control_center_dashboard_smoke", api_path)
    if spec is None or spec.loader is None:
        print(f"Unable to load {api_path}")
        return 2
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        router = getattr(module, "router", None)
        if router is None:
            print("plugin_api.py does not expose router")
            return 3
        paths = {str(getattr(route, "path", "")) for route in getattr(router, "routes", [])}
        missing = sorted(REQUIRED_ROUTES - paths)
        if missing:
            print("Missing dashboard API routes: " + ", ".join(missing))
            return 4
        print("Dashboard API import OK")
        print("Routes: " + ", ".join(sorted(paths)))
        return 0
    except Exception as exc:
        print(f"Dashboard API import failed: {type(exc).__name__}: {exc}")
        return 5
    finally:
        sys.modules.pop(spec.name, None)


if __name__ == "__main__":
    raise SystemExit(main())
