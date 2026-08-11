from __future__ import annotations

import json
from typing import Any, Callable

from .compatibility import detect_capabilities, project_unavailable_payload
from .management import ManagementCenter
from .management.overview import build_management_overview
from .task_center import TaskCenter
from .wechat import WeChatDesktop


def _result(fn: Callable[[], Any]) -> str:
    try:
        value = fn()
        return json.dumps({"ok": True, "data": value}, ensure_ascii=False, default=str)
    except Exception as exc:
        return json.dumps(
            {"ok": False, "error": type(exc).__name__, "message": str(exc)},
            ensure_ascii=False,
        )


def _resolve_cron_profile(payload: dict[str, Any]) -> dict[str, Any]:
    if str(payload.get("type") or "") != "cron" or str(payload.get("profile") or "").strip():
        return payload
    task_id = str(payload.get("id") or "").strip()
    if not task_id:
        return payload
    center = TaskCenter()
    matches = [
        job
        for job in center.cron_jobs()
        if str(job.get("id") or "") == task_id
        or str(job.get("name") or "").lower() == task_id.lower()
    ]
    profiles = sorted({str(job.get("profile") or "default") for job in matches})
    if len(profiles) == 1:
        return {**payload, "profile": profiles[0]}
    if len(profiles) > 1:
        raise ValueError(f"Cron task reference is ambiguous across profiles: {', '.join(profiles)}")
    return payload


def _project_available() -> bool:
    return detect_capabilities().project


def _unsupported_project_result() -> dict[str, Any]:
    payload = project_unavailable_payload()
    payload["capabilities"] = detect_capabilities().to_dict()
    return payload


def wechat_status(args: dict, **kwargs) -> str:
    del args, kwargs
    return _result(lambda: WeChatDesktop().status())


def wechat_list_chats(args: dict, **kwargs) -> str:
    del kwargs
    return _result(
        lambda: [row.to_dict() for row in WeChatDesktop().list_chats(int(args.get("limit", 50)))]
    )


def wechat_get_unread_chats(args: dict, **kwargs) -> str:
    del kwargs
    return _result(
        lambda: [row.to_dict() for row in WeChatDesktop().unread_chats(int(args.get("limit", 50)))]
    )


def wechat_get_messages(args: dict, **kwargs) -> str:
    del kwargs
    return _result(
        lambda: WeChatDesktop().get_messages(
            str(args.get("chat") or ""), int(args.get("limit", 20))
        )
    )


def wechat_send_message(args: dict, **kwargs) -> str:
    del kwargs
    return _result(
        lambda: WeChatDesktop().send_message(
            str(args.get("chat") or ""),
            str(args.get("text") or ""),
            dry_run=bool(args.get("dry_run", False)),
        )
    )


def task_center_overview(args: dict, **kwargs) -> str:
    del kwargs
    profile = str(args.get("profile") or "").strip() or None
    return _result(
        lambda: TaskCenter().overview(profile, bool(args.get("include_completed", False)))
    )


def task_center_upcoming(args: dict, **kwargs) -> str:
    del kwargs
    profile = str(args.get("profile") or "").strip() or None
    return _result(
        lambda: TaskCenter().upcoming(
            hours=int(args.get("hours", 168)),
            profile=profile,
            limit=int(args.get("limit", 200)),
        )
    )


def task_center_create(args: dict, **kwargs) -> str:
    del kwargs
    return _result(lambda: TaskCenter().create(dict(args)))


def task_center_update(args: dict, **kwargs) -> str:
    del kwargs
    return _result(lambda: TaskCenter().update(_resolve_cron_profile(dict(args))))


def task_center_action(args: dict, **kwargs) -> str:
    del kwargs
    return _result(lambda: TaskCenter().action(_resolve_cron_profile(dict(args))))


def task_center_history(args: dict, **kwargs) -> str:
    del kwargs
    task_type = str(args.get("type") or "")
    task_id = str(args.get("id") or "")
    profile = str(args.get("profile") or "").strip() or None
    if task_type == "cron" and profile is None:
        profile = (
            str(
                _resolve_cron_profile({"type": "cron", "id": task_id}).get("profile") or ""
            ).strip()
            or None
        )
    return _result(
        lambda: TaskCenter().history(
            task_type,
            task_id,
            limit=int(args.get("limit", 20)),
            profile=profile,
        )
    )


def management_overview(args: dict, **kwargs) -> str:
    del args, kwargs

    def load() -> dict[str, Any]:
        caps = detect_capabilities()
        return build_management_overview(
            caps=caps,
            manager=ManagementCenter(),
            task_center=TaskCenter(),
            project_unavailable_message=project_unavailable_payload()["message"],
        )

    return _result(load)


def agent_list(args: dict, **kwargs) -> str:
    del args, kwargs
    return _result(lambda: ManagementCenter().agent_list())


def agent_get(args: dict, **kwargs) -> str:
    del kwargs
    return _result(lambda: ManagementCenter().agent_get(str(args.get("name") or "")))


def agent_create(args: dict, **kwargs) -> str:
    del kwargs
    return _result(lambda: ManagementCenter().agent_create(dict(args)))


def agent_update(args: dict, **kwargs) -> str:
    del kwargs
    payload = dict(args)
    name = str(payload.pop("agent", ""))
    return _result(lambda: ManagementCenter().agent_update(name, payload))


def agent_action(args: dict, **kwargs) -> str:
    del kwargs
    name = str(args.get("name") or "")
    action = str(args.get("action") or "")
    allowed = {
        "use",
        "gateway_start",
        "gateway_stop",
        "gateway_status",
        "set_workspace",
        "export",
    }
    if action not in allowed:
        return _result(
            lambda: (_ for _ in ()).throw(ValueError("unsupported autonomous agent action"))
        )
    return _result(
        lambda: ManagementCenter().agent_action(
            name, action, str(args.get("value") or "") or None
        )
    )


def project_list(args: dict, **kwargs) -> str:
    del kwargs
    if not _project_available():
        return _result(_unsupported_project_result)
    profile = str(args.get("profile") or "").strip() or None
    include_archived = bool(args.get("include_archived", True))

    def load():
        center = ManagementCenter()
        if profile:
            return {
                "supported": True,
                "items": center.project_list(profile, include_archived),
                "partial": False,
                "errors": [],
            }
        snapshot = center.snapshot(include_archived=include_archived)
        return {
            "supported": True,
            "items": snapshot["projects"],
            "partial": snapshot["partial"],
            "errors": snapshot["errors"],
        }

    return _result(load)


def project_get(args: dict, **kwargs) -> str:
    del kwargs
    if not _project_available():
        return _result(_unsupported_project_result)
    return _result(
        lambda: ManagementCenter().project_get(
            str(args.get("project") or ""), str(args.get("profile") or "default")
        )
    )


def project_create(args: dict, **kwargs) -> str:
    del kwargs
    if not _project_available():
        return _result(
            lambda: (_ for _ in ()).throw(RuntimeError(project_unavailable_payload()["message"]))
        )
    return _result(lambda: ManagementCenter().project_create(dict(args)))


def project_update(args: dict, **kwargs) -> str:
    del kwargs
    if not _project_available():
        return _result(
            lambda: (_ for _ in ()).throw(RuntimeError(project_unavailable_payload()["message"]))
        )
    payload = dict(args)
    project = str(payload.pop("project", ""))
    profile = str(payload.pop("profile", "default"))
    return _result(lambda: ManagementCenter().project_update(project, profile, payload))


def project_action(args: dict, **kwargs) -> str:
    del kwargs
    if not _project_available():
        return _result(
            lambda: (_ for _ in ()).throw(RuntimeError(project_unavailable_payload()["message"]))
        )
    return _result(
        lambda: ManagementCenter().project_action(
            str(args.get("project") or ""),
            str(args.get("profile") or "default"),
            str(args.get("action") or ""),
            str(args.get("value") or "") or None,
        )
    )
