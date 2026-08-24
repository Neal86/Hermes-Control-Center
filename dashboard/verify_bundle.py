from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def normalized_text_bytes(path: Path) -> bytes:
    data = path.read_bytes()
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def canonical_sha256(path: Path) -> str:
    return hashlib.sha256(normalized_text_bytes(path)).hexdigest()


def canonical_git_blob_sha(path: Path) -> str:
    data = normalized_text_bytes(path)
    return hashlib.sha1(f"blob {len(data)}\0".encode("ascii") + data).hexdigest()


def verify(root: Path) -> Path:
    root = root.resolve()
    manifest_path = root / "dist" / "build-manifest.json"
    bundle = root / "dist" / "index.js"
    baseline_path = root / "source-baseline.json"
    dashboard_manifest_path = root / "manifest.json"
    for required in (manifest_path, bundle, baseline_path, dashboard_manifest_path):
        if not required.is_file():
            raise SystemExit(f"Missing Dashboard release artifact: {required}")

    release = json.loads(manifest_path.read_text("utf-8"))
    baseline = json.loads(baseline_path.read_text("utf-8"))
    dashboard_manifest = json.loads(dashboard_manifest_path.read_text("utf-8"))
    if release.get("hash_mode") != "normalized-lf-sha256":
        raise SystemExit("Unsupported Dashboard release artifact hash mode")
    if str(release.get("version") or "") != str(dashboard_manifest.get("version") or ""):
        raise SystemExit("Dashboard release artifact version does not match dashboard/manifest.json")
    if release.get("canonical_entry") != baseline.get("canonical_entry"):
        raise SystemExit("Dashboard release artifact canonical entry does not match baseline")
    if release.get("golden_main_commit") != baseline.get("golden_main_commit"):
        raise SystemExit("Dashboard release artifact baseline commit does not match source baseline")
    actual = canonical_sha256(bundle)
    if actual != str(release.get("bundle_sha256") or "").lower():
        raise SystemExit(f"Dashboard release artifact checksum mismatch: expected {release.get('bundle_sha256')}, got {actual}")
    if len(normalized_text_bytes(bundle)) != int(release.get("bundle_size_canonical") or -1):
        raise SystemExit("Dashboard release artifact canonical size mismatch")

    expected_sources = release.get("sources")
    baseline_sources = baseline.get("sources")
    if not isinstance(expected_sources, dict) or not isinstance(baseline_sources, dict):
        raise SystemExit("Dashboard release artifact source map is missing")
    for name, wanted in baseline_sources.items():
        path = root / "src" / name
        if not path.is_file():
            raise SystemExit(f"Dashboard release source missing: {name}")
        actual_source = canonical_git_blob_sha(path)
        if actual_source != str(wanted).lower() or actual_source != str(expected_sources.get(name) or "").lower():
            raise SystemExit(f"Dashboard release source checksum mismatch: {name}")
    return bundle


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    print(verify(args.root))


if __name__ == "__main__":
    main()
