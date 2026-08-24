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
    "resource_selector_v5.js",
    "components.js",
    "app.js",
    "control_center_v2.js",
    "provider_models_v3.js",
    "focus_guard.js",
    "cdp_import_v4.js",
]
CANONICAL_ENTRY = "canonical_ui.js"
REGISTER_ENTRY = "index.js"
POST_REGISTER_ORDER = ["version_badge.js"]
ORDER = COMPATIBILITY_ORDER + [CANONICAL_ENTRY, REGISTER_ENTRY] + POST_REGISTER_ORDER
BASELINE_FILE = "source-baseline.json"
RELEASE_MANIFEST = "build-manifest.json"


def normalized_text_bytes(path: Path) -> bytes:
    data = path.read_bytes()
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def canonical_git_blob_sha(path: Path) -> str:
    data = normalized_text_bytes(path)
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def canonical_sha256(path: Path) -> str:
    return hashlib.sha256(normalized_text_bytes(path)).hexdigest()


def validate_baseline(root: Path, src: Path) -> dict:
    baseline_path = root / BASELINE_FILE
    if not baseline_path.is_file():
        raise SystemExit(f"Missing dashboard baseline lock: {baseline_path}")
    try:
        baseline = json.loads(baseline_path.read_text("utf-8"))
    except Exception as exc:
        raise SystemExit(f"Invalid dashboard baseline lock: {exc}") from exc

    if baseline.get("canonical_entry") != f"src/{CANONICAL_ENTRY}":
        raise SystemExit(f"Dashboard baseline canonical entry mismatch: expected src/{CANONICAL_ENTRY}")
    if baseline.get("hash_mode") != "normalized-lf-git-blob-sha1":
        raise SystemExit("Dashboard baseline hash mode is missing or unsupported")

    expected = baseline.get("sources")
    if not isinstance(expected, dict):
        raise SystemExit("Dashboard baseline lock has no sources map")

    locked = COMPATIBILITY_ORDER + [CANONICAL_ENTRY]
    missing_locks = [name for name in locked if not expected.get(name)]
    if missing_locks:
        raise SystemExit("Dashboard baseline is incomplete; missing locks for: " + ", ".join(missing_locks))

    drift = []
    for name in locked:
        path = src / name
        if not path.is_file():
            drift.append(f"{name}: missing")
            continue
        actual = canonical_git_blob_sha(path)
        wanted = str(expected[name]).strip().lower()
        if actual != wanted:
            drift.append(f"{name}: expected {wanted}, got {actual}")
    if drift:
        raise SystemExit(
            "Dashboard source baseline drift detected. Refusing to build from changed UI source. "
            "Line-ending-only CRLF/LF differences are ignored.\n  " + "\n  ".join(drift)
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
    out.write_text(banner + body, "utf-8", newline="\n")

    dashboard_manifest = json.loads((root / "manifest.json").read_text("utf-8"))
    release_manifest = {
        "schema": 1,
        "version": str(dashboard_manifest.get("version") or ""),
        "canonical_entry": baseline.get("canonical_entry"),
        "golden_main_commit": golden,
        "hash_mode": "normalized-lf-sha256",
        "bundle": "dist/index.js",
        "bundle_sha256": canonical_sha256(out),
        "bundle_size_canonical": len(normalized_text_bytes(out)),
        "sources": {name: canonical_git_blob_sha(src / name) for name in COMPATIBILITY_ORDER + [CANONICAL_ENTRY]},
    }
    (out_dir / RELEASE_MANIFEST).write_text(
        json.dumps(release_manifest, indent=2, sort_keys=True) + "\n", "utf-8", newline="\n"
    )
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    print(build(args.root))


if __name__ == "__main__":
    main()
