"""Hermes Control Center plugin entry point."""

from collections.abc import Iterable
from typing import Any

from .compatibility import detect_capabilities, install_hermes_cli_compat

install_hermes_cli_compat()

from . import schemas, tools  # noqa: E402
from .gateway_isolation import install_independent_gateway_policy  # noqa: E402
from .resources import tools as resource_tools  # noqa: E402
from .resources.policy import pre_tool_call as resource_pre_tool_call  # noqa: E402

install_independent_gateway_policy()

ToolSpec = tuple[str, dict[str, Any], Any]


def _register_group(ctx, toolset: str, specs: Iterable[ToolSpec], *, check_fn=None) -> None:
    for name, schema, handler in specs:
        kwargs = {
            "name": name,
            "toolset": toolset,
            "schema": schema,
            "handler": handler,
            "description": schema["description"],
        }
        if check_fn is not None:
            kwargs["check_fn"] = check_fn
        ctx.register_tool(**kwargs)


def register(ctx):
    register_hook = getattr(ctx, "register_hook", None)
    if callable(register_hook):
        register_hook("pre_tool_call", resource_pre_tool_call)

    _register_group(
        ctx,
        "hermes_control_center_resources",
        [
            ("resource_list", resource_tools.RESOURCE_LIST, resource_tools.resource_list),
            ("bound_browser", resource_tools.BOUND_BROWSER, resource_tools.bound_browser),
        ],
    )

    _register_group(
        ctx,
        "hermes_extensions_wechat",
        [
            ("wechat_status", schemas.WECHAT_STATUS, resource_tools.wechat_status),
            ("wechat_list_chats", schemas.WECHAT_LIST_CHATS, resource_tools.wechat_list_chats),
            ("wechat_get_unread_chats", schemas.WECHAT_GET_UNREAD_CHATS, resource_tools.wechat_get_unread_chats),
            ("wechat_get_messages", schemas.WECHAT_GET_MESSAGES, resource_tools.wechat_get_messages),
            ("wechat_send_message", schemas.WECHAT_SEND_MESSAGE, resource_tools.wechat_send_message),
        ],
        check_fn=resource_tools.bound_wechat_available,
    )

    _register_group(
        ctx,
        "hermes_extensions_tasks",
        [
            ("task_center_overview", schemas.TASK_CENTER_OVERVIEW, tools.task_center_overview),
            ("task_center_upcoming", schemas.TASK_CENTER_UPCOMING, tools.task_center_upcoming),
            ("task_center_create", schemas.TASK_CENTER_CREATE, tools.task_center_create),
            ("task_center_update", schemas.TASK_CENTER_UPDATE, tools.task_center_update),
            ("task_center_action", schemas.TASK_CENTER_ACTION, tools.task_center_action),
            ("task_center_history", schemas.TASK_CENTER_HISTORY, tools.task_center_history),
        ],
    )

    management_specs: list[ToolSpec] = [
        ("management_overview", schemas.MANAGEMENT_OVERVIEW, tools.management_overview),
        ("agent_list", schemas.AGENT_LIST, tools.agent_list),
        ("agent_get", schemas.AGENT_GET, tools.agent_get),
        ("agent_create", schemas.AGENT_CREATE, tools.agent_create),
        ("agent_update", schemas.AGENT_UPDATE, tools.agent_update),
        ("agent_action", schemas.AGENT_ACTION, tools.agent_action),
    ]
    if detect_capabilities().project:
        management_specs.extend(
            [
                ("project_list", schemas.PROJECT_LIST, tools.project_list),
                ("project_get", schemas.PROJECT_GET, tools.project_get),
                ("project_create", schemas.PROJECT_CREATE, tools.project_create),
                ("project_update", schemas.PROJECT_UPDATE, tools.project_update),
                ("project_action", schemas.PROJECT_ACTION, tools.project_action),
            ]
        )
    _register_group(ctx, "hermes_extensions_management", management_specs)
