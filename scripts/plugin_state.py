from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import yaml

TARGETS = ("hermes-extensions", "wechat-desktop")


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


def normalize(config_path: Path, mode: str = "finalize") -> None:
    raw = yaml.safe_load(config_path.read_text("utf-8")) if config_path.exists() else {}
    cfg = raw if isinstance(raw, dict) else {}
    plugins = cfg.get("plugins")
    if not isinstance(plugins, dict):
        plugins = {}
        cfg["plugins"] = plugins

    enabled = _clean_list(plugins.get("enabled"))
    disabled = _clean_list(plugins.get("disabled"))
    disabled = [item for item in disabled if item not in TARGETS]

    if mode == "finalize":
        for name in TARGETS:
            if name not in enabled:
                enabled.append(name)
    elif mode != "prepare":
        raise ValueError("mode must be prepare or finalize")

    plugins["enabled"] = enabled
    plugins["disabled"] = disabled
    _write(config_path, cfg)

    verify = yaml.safe_load(config_path.read_text("utf-8")) or {}
    state = verify.get("plugins") or {}
    for name in TARGETS:
        if name in (state.get("disabled") or []):
            raise RuntimeError(f"still present in plugins.disabled: {name}")
        if mode == "finalize" and name not in (state.get("enabled") or []):
            raise RuntimeError(f"missing from plugins.enabled: {name}")


if __name__ == "__main__":
    if len(sys.argv) not in {2, 3}:
        raise SystemExit("usage: plugin_state.py <config.yaml> [prepare|finalize]")
    mode = sys.argv[2] if len(sys.argv) == 3 else "finalize"
    normalize(Path(sys.argv[1]).expanduser().resolve(), mode)
    print(f"Plugin state {mode} complete: hermes-extensions, wechat-desktop")
