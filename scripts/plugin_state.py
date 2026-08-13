from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import yaml


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
        if name not in out:
            out.append(name)
    return out


def normalize(config_path: Path) -> None:
    raw = yaml.safe_load(config_path.read_text("utf-8")) if config_path.exists() else {}
    cfg = raw if isinstance(raw, dict) else {}
    plugins = cfg.get("plugins")
    if not isinstance(plugins, dict):
        plugins = {}
        cfg["plugins"] = plugins

    enabled = _clean_list(plugins.get("enabled"))
    disabled = _clean_list(plugins.get("disabled"))
    for name in ("hermes-extensions", "wechat-desktop"):
        if name not in enabled:
            enabled.append(name)
        disabled = [item for item in disabled if item != name]

    plugins["enabled"] = enabled
    plugins["disabled"] = disabled
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

    verify = yaml.safe_load(config_path.read_text("utf-8")) or {}
    state = verify.get("plugins") or {}
    for name in ("hermes-extensions", "wechat-desktop"):
        if name not in (state.get("enabled") or []):
            raise RuntimeError(f"missing from plugins.enabled: {name}")
        if name in (state.get("disabled") or []):
            raise RuntimeError(f"still present in plugins.disabled: {name}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: plugin_state.py <config.yaml>")
    normalize(Path(sys.argv[1]).expanduser().resolve())
    print("Plugin state normalized: hermes-extensions, wechat-desktop")
