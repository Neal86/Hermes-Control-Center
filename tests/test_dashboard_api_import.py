from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError


ROOT = Path(__file__).resolve().parents[1]
API_PATH = ROOT / "dashboard" / "plugin_api.py"


def load_dashboard_api():
    name = "hx_dashboard_api_test"
    spec = importlib.util.spec_from_file_location(name, API_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_dashboard_api_imports_with_dataclass_compatibility_module() -> None:
    api = load_dashboard_api()
    caps = api.compat.HermesCapabilities(
        hermes=True,
        plugins=True,
        dashboard=True,
        profile=True,
        project=False,
        cron=True,
        kanban=True,
    )
    assert caps.project is False
    assert api.router.routes


def test_dashboard_write_bodies_forbid_unknown_fields() -> None:
    api = load_dashboard_api()
    with pytest.raises(ValidationError):
        api.AgentBody(name="support", unexpected="should-fail")
