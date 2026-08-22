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


def test_dashboard_dynamic_management_center_gets_independent_gateway_policy(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    config_path = tmp_path / "config.yaml"
    config_path.write_text("gateway:\n  multiplex_profiles: true\n", "utf-8")

    api = load_dashboard_api()

    assert getattr(api.ManagementCenter, "_hcc_independent_gateway_policy_installed", False) is True
    assert api.ManagementCenter._gateway_multiplexes_profiles(object()) is False
    assert "multiplex_profiles: false" in config_path.read_text("utf-8")
