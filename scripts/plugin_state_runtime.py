from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import yaml

REQUIRED = ("hermes-extensions", "wechat-desktop")


def clean(value):
    result = []
    if not isinstance(value, list):
        return result
    for item in value:
        name = str(item or "").strip().replace("\\", "/")
        low = name.lower()
        if not name:
            continue
        if ".hermes-control-center-txn-" in low:
            continue
        if "backup-hermes-extensions" in low or "backup-wechat-desktop" in low:
            continue
        if name not in result:
            result.append(name)
    return result


def write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix="config.", suffix=".yaml.tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            yaml.safe_dump(data, handle, sort_keys=False, allow_unicode=True)
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except OSError:
            pass


def normalize(path: Path, mode: str) -> None:
    raw = yaml.safe_load(path.read_text("utf-8")) if path.exists() else {}
    cfg = raw if isinstance(raw, dict) else {}
    plugins = cfg.get("plugins")
    if not isinstance(plugins, dict):
        plugins = {}
        cfg["plugins"] = plugins

    enabled = clean(plugins.get("enabled"))
    disabled = [x for x in clean(plugins.get("disabled")) if x not in REQUIRED]
    if mode == "finalize":
        for name in REQUIRED:
            if name not in enabled:
                enabled.append(name)
    elif mode != "prepare":
        raise SystemExit("mode must be prepare or finalize")

    plugins["enabled"] = enabled
    plugins["disabled"] = disabled
    write_yaml(path, cfg)
    print("Runtime plugin state: " + ", ".join(REQUIRED))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: plugin_state_runtime.py <config.yaml> <prepare|finalize>")
    normalize(Path(sys.argv[1]).expanduser().resolve(), sys.argv[2])
