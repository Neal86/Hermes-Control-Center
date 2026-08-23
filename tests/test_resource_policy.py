from __future__ import annotations

from resources import policy


def test_wechat_binding_does_not_block_clarify(monkeypatch):
    monkeypatch.setattr(policy, "current_agent", lambda: "11")
    assert policy.pre_tool_call("clarify", {"question": "Please confirm the order lookup"}) is None


def test_wechat_binding_does_not_block_computer_use(monkeypatch):
    monkeypatch.setattr(policy, "current_agent", lambda: "11")
    assert policy.pre_tool_call("computer_use", {"action": "click"}) is None


def test_agent_browser_policy_still_applies(monkeypatch):
    monkeypatch.setattr(policy, "current_agent", lambda: "11")

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


def test_browser_without_binding_still_fails_closed(monkeypatch):
    monkeypatch.setattr(policy, "current_agent", lambda: "11")

    class MissingBindings:
        def require(self, agent, kind, ready=True):
            raise policy.ResourceAccessError("missing browser")

    monkeypatch.setattr(policy, "ResourceBindings", MissingBindings)
    result = policy.pre_tool_call("browser_exec", {"action": "read"})
    assert result is not None
    assert result["action"] == "block"
    assert "missing browser" in result["message"]
