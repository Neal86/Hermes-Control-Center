from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def copy_dashboard(tmp_path: Path) -> Path:
    target = tmp_path / "dashboard"
    shutil.copytree(ROOT / "dashboard", target)
    return target


def test_baseline_hash_ignores_crlf_vs_lf(tmp_path: Path) -> None:
    target = copy_dashboard(tmp_path)
    build = load_module(target / "build_bundle.py", "hcc_build_eol")
    source = target / "src" / "api.js"
    lf = source.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    source.write_bytes(lf)
    first = build.canonical_git_blob_sha(source)
    source.write_bytes(lf.replace(b"\n", b"\r\n"))
    second = build.canonical_git_blob_sha(source)
    assert first == second
    build.validate_baseline(target, target / "src")


def test_baseline_hash_rejects_real_source_change(tmp_path: Path) -> None:
    target = copy_dashboard(tmp_path)
    build = load_module(target / "build_bundle.py", "hcc_build_drift")
    source = target / "src" / "api.js"
    source.write_text(source.read_text("utf-8") + "\n// real drift\n", "utf-8")
    with pytest.raises(SystemExit, match="baseline drift"):
        build.validate_baseline(target, target / "src")


def test_release_artifact_verifier_ignores_eol_but_detects_content_change(tmp_path: Path) -> None:
    target = copy_dashboard(tmp_path)
    build = load_module(target / "build_bundle.py", "hcc_build_release")
    verify = load_module(target / "verify_bundle.py", "hcc_verify_release")
    bundle = build.build(target)
    verify.verify(target)
    lf = bundle.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    bundle.write_bytes(lf.replace(b"\n", b"\r\n"))
    verify.verify(target)
    bundle.write_bytes(bundle.read_bytes() + b"\n// tampered\n")
    with pytest.raises(SystemExit, match="checksum mismatch"):
        verify.verify(target)


def test_release_manifest_matches_versions_and_source_baseline() -> None:
    release = json.loads((ROOT / "dashboard" / "dist" / "build-manifest.json").read_text("utf-8"))
    manifest = json.loads((ROOT / "dashboard" / "manifest.json").read_text("utf-8"))
    baseline = json.loads((ROOT / "dashboard" / "source-baseline.json").read_text("utf-8"))
    assert release["version"] == manifest["version"]
    assert release["golden_main_commit"] == baseline["golden_main_commit"]
    assert release["hash_mode"] == "normalized-lf-sha256"


def test_installer_defaults_to_prebuilt_release_artifact() -> None:
    installer = (ROOT / "install.ps1").read_text("utf-8")
    assert "[switch]$BuildDashboardFromSource" in installer
    assert 'if ($BuildDashboardFromSource)' in installer
    assert 'Using prebuilt Dashboard/Web release artifact' in installer
    assert 'dashboard\\verify_bundle.py' in installer
    assert 'dashboard\\dist\\build-manifest.json' in installer
