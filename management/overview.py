from __future__ import annotations

import sys
from typing import Any


def _resolved_defaults() -> tuple[Any, Any, Any, str]:
    """Reuse Dashboard's stable dynamic modules when present."""
    compat = sys.modules.get("hermes_extensions_compatibility")
    management = sys.modules.get("hermes_extensions_management_service")
    task_module = sys.modules.get("hermes_extensions_task_center_service")

    if compat is None:
        import compatibility as compat  # type: ignore[no-redef]
    if management is None:
        import management.service as management  # type: ignore[no-redef]
    if task_module is None:
        import task_center as task_module  # type: ignore[no-redef]

    caps = compat.detect_capabilities()
    manager = management.ManagementCenter()
    task_center = task_module.TaskCenter()
    message = compat.project_unavailable_payload()["message"]
    return caps, manager, task_center, message


def build_management_overview(
    *,
    caps: Any | None = None,
    manager: Any | None = None,
    task_center: Any | None = None,
    project_unavailable_message: str | None = None,
) -> dict[str, Any]:
    """Build the canonical management/task summary used by UI and tools."""
    if (
        caps is None
        or manager is None
        or task_center is None
        or project_unavailable_message is None
    ):
        default_caps, default_manager, default_tasks, default_message = _resolved_defaults()
        caps = caps if caps is not None else default_caps
        manager = manager if manager is not None else default_manager
        task_center = task_center if task_center is not None else default_tasks
        project_unavailable_message = (
            project_unavailable_message
            if project_unavailable_message is not None
            else default_message
        )

    if caps.project:
        data = manager.overview()
    else:
        agents = manager.agent_list(probe_runtime=True)
        errors = [
            {"scope": f"agent:{agent['name']}", "message": str(agent["status_error"])}
            for agent in agents
            if agent.get("status_error")
        ]
        errors.append({"scope": "projects", "message": project_unavailable_message})
        data = {
            "counts": {
                "agents": len(agents),
                "running_agents": sum(
                    1
                    for agent in agents
                    if str(agent.get("gateway") or "").lower().startswith("running")
                ),
                "projects": 0,
                "archived_projects": 0,
            },
            "agents": agents,
            "projects": [],
            "active_profile": manager._active_profile(),
            "partial": True,
            "errors": errors,
        }

    tasks = task_center.overview(include_completed=False)
    data["task_counts"] = tasks.get("counts", {})
    data["upcoming"] = task_center.upcoming(hours=24 * 7, limit=25)
    if tasks.get("kanban_error"):
        data.setdefault("errors", []).append(
            {"scope": "tasks:kanban", "message": str(tasks["kanban_error"])}
        )
        data["partial"] = True
    data["capabilities"] = caps.to_dict()
    data["project_supported"] = caps.project
    return data
