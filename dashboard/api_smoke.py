from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


REQUIRED_ROUTES = {
    "/management/overview",
    "/agents",
    "/providers",
    "/resources",
}


def main() -> int:
    dashboard_root = Path(__file__).resolve().parent
    plugin_root = dashboard_root.parent
    if str(plugin_root) not in sys.path:
        sys.path.insert(0, str(plugin_root))
    if str(dashboard_root) not in sys.path:
        sys.path.insert(0, str(dashboard_root))

    try:
        manifest = json.loads((dashboard_root / "manifest.json").read_text("utf-8"))
    except Exception as exc:
        print(f"Unable to read dashboard manifest: {type(exc).__name__}: {exc}")
        return 2

    api_rel = str(manifest.get("api") or "").strip()
    if not api_rel:
        print("Dashboard manifest does not define api")
        return 2
    api_path = dashboard_root / api_rel
    if not api_path.is_file():
        print(f"Dashboard API target does not exist: {api_path}")
        return 2

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
            print(f"{api_rel} does not expose router")
            return 3
        paths = {str(getattr(route, "path", "")) for route in getattr(router, "routes", [])}
        missing = sorted(REQUIRED_ROUTES - paths)
        if missing:
            print("Missing dashboard API routes: " + ", ".join(missing))
            return 4
        print(f"Dashboard API import OK: {api_rel}")
        print("Routes: " + ", ".join(sorted(paths)))
        return 0
    except Exception as exc:
        print(f"Dashboard API import failed: {type(exc).__name__}: {exc}")
        return 5
    finally:
        sys.modules.pop(spec.name, None)


if __name__ == "__main__":
    raise SystemExit(main())
