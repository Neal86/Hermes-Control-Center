from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]


class FakeContext:
    def __init__(self) -> None:
        self.tools = {}

    def register_tool(self, **kwargs) -> None:
        self.tools[kwargs["name"]] = kwargs


def load_plugin():
    name = "hx_plugin_test_package"
    spec = importlib.util.spec_from_file_location(name, ROOT / "__init__.py", submodule_search_locations=[str(ROOT)])
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _base_tools() -> set[str]:
    return {
        "wechat_status", "wechat_list_chats", "wechat_get_unread_chats", "wechat_get_messages", "wechat_send_message",
        "task_center_overview", "task_center_upcoming", "task_center_create", "task_center_update", "task_center_action", "task_center_history",
        "management_overview", "agent_list", "agent_get", "agent_create", "agent_update", "agent_action",
    }


def _project_tools() -> set[str]:
    return {"project_list", "project_get", "project_create", "project_update", "project_action"}


def test_registers_project_tools_when_native_projects_exist() -> None:
    plugin = load_plugin()
    plugin.detect_capabilities = lambda: SimpleNamespace(project=True)
    ctx = FakeContext()
    plugin.register(ctx)
    assert set(ctx.tools) == _base_tools() | _project_tools()
    assert ctx.tools["wechat_send_message"]["toolset"] == "hermes_extensions_wechat"
    assert ctx.tools["task_center_overview"]["toolset"] == "hermes_extensions_tasks"
    assert ctx.tools["management_overview"]["toolset"] == "hermes_extensions_management"
    assert callable(ctx.tools["wechat_status"]["check_fn"])


def test_hides_project_tools_when_native_projects_are_unavailable() -> None:
    plugin = load_plugin()
    plugin.detect_capabilities = lambda: SimpleNamespace(project=False)
    ctx = FakeContext()
    plugin.register(ctx)
    assert set(ctx.tools) == _base_tools()
    assert not (_project_tools() & set(ctx.tools))
