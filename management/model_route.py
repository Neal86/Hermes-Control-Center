from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import yaml


def _read_config(home: Path) -> dict[str, Any]:
    path = home / "config.yaml"
    try:
        value = yaml.safe_load(path.read_text("utf-8")) if path.exists() else {}
    except (OSError, yaml.YAMLError):
        value = {}
    return value if isinstance(value, dict) else {}


def _write_config(home: Path, config: dict[str, Any]) -> None:
    path = home / "config.yaml"
    home.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="config.", suffix=".yaml.tmp", dir=str(home))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            yaml.safe_dump(config, handle, sort_keys=False, allow_unicode=True)
        Path(tmp).replace(path)
    finally:
        try:
            Path(tmp).unlink(missing_ok=True)
        except OSError:
            pass


def sync_model_route(home: Path, *, provider: str | None = None, model: str | None = None) -> dict[str, str]:
    from hermes_cli.providers import determine_api_mode, resolve_provider_full

    home = home.expanduser().resolve()
    config = _read_config(home)
    model_cfg = config.get("model")
    if not isinstance(model_cfg, dict):
        model_cfg = {}
        config["model"] = model_cfg

    target_provider = str(provider if provider is not None else model_cfg.get("provider") or "").strip()
    target_model = str(model if model is not None else model_cfg.get("default") or "").strip()
    if not target_provider:
        raise ValueError("model.provider cannot be empty")
    if not target_model:
        raise ValueError("model.default cannot be empty")

    user_providers = config.get("providers") if isinstance(config.get("providers"), dict) else {}
    custom_providers = config.get("custom_providers") if isinstance(config.get("custom_providers"), list) else []
    pdef = resolve_provider_full(target_provider, user_providers=user_providers, custom_providers=custom_providers)
    if pdef is None:
        raise ValueError(f"unknown Hermes provider: {target_provider}")

    base_url = str(getattr(pdef, "base_url", "") or "").strip()
    api_mode = determine_api_mode(target_provider, base_url=base_url, model=target_model)
    model_cfg["provider"] = target_provider
    model_cfg["default"] = target_model
    if base_url:
        model_cfg["base_url"] = base_url
    else:
        model_cfg.pop("base_url", None)
    if api_mode:
        model_cfg["api_mode"] = api_mode
    else:
        model_cfg.pop("api_mode", None)

    _write_config(home, config)
    return {"provider": target_provider, "model": target_model, "base_url": base_url, "api_mode": str(api_mode or "")}
