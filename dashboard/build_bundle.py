from __future__ import annotations

import argparse
from pathlib import Path

ORDER = [
    "api.js",
    "components.js",
    "app.js",
    "control_center_v2.js",
    "provider_models_v3.js",
    "focus_guard.js",
    "cdp_import_v4.js",
    "index.js",
]


def build(root: Path) -> Path:
    root = root.resolve()
    src = root / "src"
    missing = [name for name in ORDER if not (src / name).is_file()]
    if missing:
        raise SystemExit(f"Missing dashboard source modules: {', '.join(missing)}")
    out_dir = root / "dist"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "index.js"
    banner = "/* Hermes Control Center dashboard bundle. Generated from dashboard/src modules. */\n"
    body = "\n\n".join((src / name).read_text("utf-8").rstrip() for name in ORDER) + "\n"
    out.write_text(banner + body, "utf-8")
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    print(build(args.root))


if __name__ == "__main__":
    main()
