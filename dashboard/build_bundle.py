from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

# Compatibility modules may prepare/extend the UI, but none of them is the
# registration entry. canonical_ui.js snapshots and locks the final app, and
# index.js registers only that canonical app with Hermes.
COMPATIBILITY_ORDER = [
    "api.js",
    "components.js",
    "app.js",
    "control_center_v2.js",
    "provider_models_v3.js",
    "focus_guard.js",
    "cdp_import_v4.js",
]
CANONICAL_ENTRY = "canonical_ui.js"
REGISTER_ENTRY = "index.js"
ORDER = COMPATIBILITY_ORDER + [CANONICAL_ENTRY, REGISTER_ENTRY]
BASELINE_FILE = "source-baseline.json"


def git_blob_sha(path: Path) -> str:
    data = path.read_bytes()
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def validate_baseline(root: Path, src: Path) -> dict:
    baseline_path = root / BASELINE_FILE
    if not baseline_path.is_file():
        raise SystemExit(f"Missing dashboard baseline lock: {baseline_path}")
    try:
        baseline = json.loads(baseline_path.read_text("utf-8"))
    except Exception as exc:
        raise SystemExit(f"Invalid dashboard baseline lock: {exc}") from exc

    if baseline.get("canonical_entry") != f"src/{CANONICAL_ENTRY}":
        raise SystemExit(
            "Dashboard baseline canonical entry mismatch: expected "
            f"src/{CANONICAL_ENTRY}"
        )

    expected = baseline.get("sources")
    if not isinstance(expected, dict):
        raise SystemExit("Dashboard baseline lock has no sources map")

    locked = COMPATIBILITY_ORDER + [CANONICAL_ENTRY]
    missing_locks = [name for name in locked if not expected.get(name)]
    if missing_locks:
        raise SystemExit(
            "Dashboard baseline is incomplete; missing locks for: "
            + ", ".join(missing_locks)
        )

    drift = []
    for name in locked:
        path = src / name
        if not path.is_file():
            drift.append(f"{name}: missing")
            continue
        actual = git_blob_sha(path)
        wanted = str(expected[name]).strip().lower()
        if actual != wanted:
            drift.append(f"{name}: expected {wanted}, got {actual}")
    if drift:
        raise SystemExit(
            "Dashboard source baseline drift detected. Refusing to build from a "
            "silently changed/older UI module. Start from the current main HEAD "
            "and explicitly refresh dashboard/source-baseline.json for intentional "
            "changes.\n  " + "\n  ".join(drift)
        )
    return baseline


def build(root: Path) -> Path:
    root = root.resolve()
    src = root / "src"
    missing = [name for name in ORDER if not (src / name).is_file()]
    if missing:
        raise SystemExit(f"Missing dashboard source modules: {', '.join(missing)}")

    baseline = validate_baseline(root, src)

    out_dir = root / "dist"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "index.js"
    golden = str(baseline.get("golden_main_commit") or "unknown")
    banner = (
        "/* Hermes Control Center dashboard bundle. "
        "Single canonical UI entry: canonical_ui.js. "
        f"Golden baseline: {golden}. */\n"
    )
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
