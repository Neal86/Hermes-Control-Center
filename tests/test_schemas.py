from __future__ import annotations

import schemas


def test_task_action_is_enum_constrained() -> None:
    action = schemas.TASK_CENTER_ACTION["parameters"]["properties"]["action"]
    assert action["enum"] == ["pause", "resume", "run", "remove", "assign", "archive"]
    assert schemas.TASK_CENTER_ACTION["parameters"]["additionalProperties"] is False


def test_autonomous_agent_action_excludes_restart_and_delete() -> None:
    allowed = schemas.AGENT_ACTION["parameters"]["properties"]["action"]["enum"]
    assert "gateway_restart" not in allowed
    assert "delete" not in allowed
    assert {"gateway_start", "gateway_stop", "gateway_status"} <= set(allowed)


def test_management_overview_contract_mentions_tasks() -> None:
    text = schemas.MANAGEMENT_OVERVIEW["description"].lower()
    assert "task counts" in text
    assert "seven days" in text
