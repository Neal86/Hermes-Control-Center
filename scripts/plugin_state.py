from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

import yaml

PRIMARY = "hermes-extensions"
LEGACY = "wechat-desktop"


def _clean_list(value):
    out: list[str] = []
    if not isinstance(value, list):
        return out
    for item in value:
        name = str(item or "").strip().replace("\\", "/")
        low = name.lower()
        if not name:
            continue
        if ".hermes-control-center-txn-" in low:
            continue
        if "backup-hermes-extensions" in low or "backup-wechat-desktop" in low:
            continue
        if name == LEGACY:
            continue
        if name not in out:
            out.append(name)
    return out


def _write(config_path: Path, cfg: dict) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix="config.", suffix=".yaml.tmp", dir=str(config_path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            yaml.safe_dump(cfg, handle, sort_keys=False, allow_unicode=True)
        os.replace(tmp_name, config_path)
    finally:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass


def _remove_legacy_runtime(config_path: Path) -> None:
    hermes_home = config_path.parent
    for path in (
        hermes_home / "plugins" / LEGACY,
        hermes_home / "plugins" / "platforms" / LEGACY,
    ):
        if path.exists():
            shutil.rmtree(path, ignore_errors=False)


def normalize(config_path: Path, mode: str = "finalize") -> None:
    raw = yaml.safe_load(config_path.read_text("utf-8")) if config_path.exists() else {}
    cfg = raw if isinstance(raw, dict) else {}
    plugins = cfg.get("plugins")
    if not isinstance(plugins, dict):
        plugins = {}
        cfg["plugins"] = plugins

    enabled = _clean_list(plugins.get("enabled"))
    disabled = _clean_list(plugins.get("disabled"))
    disabled = [item for item in disabled if item not in {PRIMARY, LEGACY}]

    if mode == "finalize":
        if PRIMARY not in enabled:
            enabled.append(PRIMARY)
    elif mode != "prepare":
        raise ValueError("mode must be prepare or finalize")

    plugins["enabled"] = enabled
    plugins["disabled"] = disabled
    _write(config_path, cfg)

    if mode == "finalize":
        _remove_legacy_runtime(config_path)

    verify = yaml.safe_load(config_path.read_text("utf-8")) or {}
    state = verify.get("plugins") or {}
    if PRIMARY in (state.get("disabled") or []):
        raise RuntimeError(f"still present in plugins.disabled: {PRIMARY}")
    if LEGACY in (state.get("enabled") or []) or LEGACY in (state.get("disabled") or []):
        raise RuntimeError(f"legacy standalone plugin entry still present: {LEGACY}")
    if mode == "finalize" and PRIMARY not in (state.get("enabled") or []):
        raise RuntimeError(f"missing from plugins.enabled: {PRIMARY}")
    if mode == "finalize" and (config_path.parent / "plugins" / LEGACY).exists():
        raise RuntimeError(f"legacy standalone plugin directory still exists: {LEGACY}")


if __name__ == "__main__":
    if len(sys.argv) not in {2, 3}:
        raise SystemExit("usage: plugin_state.py <config.yaml> [prepare|finalize]")
    mode = sys.argv[2] if len(sys.argv) == 3 else "finalize"
    normalize(Path(sys.argv[1]).expanduser().resolve(), mode)
    print(f"Plugin state {mode} complete: {PRIMARY}; removed legacy {LEGACY}")
