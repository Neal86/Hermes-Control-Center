from __future__ import annotations

from resources import policy


def _bound_wechat(monkeypatch):
    monkeypatch.setattr(policy, "current_agent", lambda: "11")
    monkeypatch.setattr(policy, "_agent_has_bound_wechat", lambda agent: agent == "11")


def test_wechat_bound_agent_blocks_interactive_clarify(monkeypatch):
    _bound_wechat(monkeypatch)

    result = policy.pre_tool_call(
        "clarify",
        {"question": "Please confirm the order lookup"},
        task_id="task-1",
    )

    assert result is not None
    assert result["action"] == "block"
    message = result["message"]
    assert "unavailable" in message.lower()
    assert "continue immediately" in message.lower()
    assert "normal assistant reply" in message.lower()


def test_non_wechat_agent_keeps_clarify_available(monkeypatch):
    monkeypatch.setattr(policy, "current_agent", lambda: "12")
    monkeypatch.setattr(policy, "_agent_has_bound_wechat", lambda agent: False)

    assert policy.pre_tool_call("clarify", {"question": "Need info"}) is None


def test_wechat_bound_agent_browser_policy_still_applies(monkeypatch):
    _bound_wechat(monkeypatch)

    class FakeBindings:
        def require(self, agent, kind, ready=True):
            assert agent == "11"
            assert kind == "browser"
            assert ready is True
            return {"id": "browser:test", "debug_port": 9222}

    monkeypatch.setattr(policy, "ResourceBindings", FakeBindings)
    monkeypatch.delenv("BROWSER_CDP_URL", raising=False)
    monkeypatch.delenv("HERMES_CONTROL_CENTER_BROWSER_RESOURCE", raising=False)

    assert policy.pre_tool_call("browser_exec", {"action": "read"}) is None
    assert policy.os.environ["BROWSER_CDP_URL"] == "http://127.0.0.1:9222"
    assert policy.os.environ["HERMES_CONTROL_CENTER_BROWSER_RESOURCE"] == "browser:test"


def test_wechat_bound_agent_computer_use_remains_blocked(monkeypatch):
    _bound_wechat(monkeypatch)

    result = policy.pre_tool_call("computer_use", {"action": "click"})

    assert result is not None
    assert result["action"] == "block"
    assert "blocked computer_use" in result["message"]
