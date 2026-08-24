from business_guard import _evidence_state, pre_llm_call


def _call(name, args):
    return {"role": "assistant", "tool_calls": [{"function": {"name": name, "arguments": args}}]}


def test_generic_chrome_capture_is_not_business_evidence():
    msg = "OBS0402608230VX order status"
    history = [
        {"role": "user", "content": msg},
        _call("computer_use", '{"action":"capture","app":"Chrome","mode":"som"}'),
        {"role": "tool", "tool_name": "computer_use", "content": "Chrome tabs: Gmail, Google, ChatGPT"},
    ]
    state = _evidence_state(history, msg)
    assert state["tool_activity"] is True
    assert state["query_submitted"] is False
    assert state["verified_minimum"] is False
    ctx = pre_llm_call(platform="wechat_desktop", user_message=msg, conversation_history=history)
    assert ctx and "MUST CONTINUE" in ctx["context"]
    assert "NOT business evidence" in ctx["context"]


def test_old_not_found_answer_does_not_count_for_new_turn():
    msg = "OBS0402608230VX order status"
    history = [
        {"role": "user", "content": msg},
        {"role": "assistant", "content": "not found"},
        {"role": "user", "content": msg},
    ]
    state = _evidence_state(history, msg)
    assert state["verified_minimum"] is False
    assert state["tool_activity"] is False


def test_identifier_submit_plus_result_read_can_satisfy_minimum():
    msg = "OBS0402608230VX order status"
    history = [
        {"role": "user", "content": msg},
        _call("browser_type", '{"text":"OBS0402608230VX"}'),
        {"role": "tool", "tool_name": "browser_type", "content": '{"success":true}'},
        _call("browser_snapshot", '{}'),
        {"role": "tool", "tool_name": "browser_snapshot", "content": "Order OBS0402608230VX status: shipped"},
    ]
    state = _evidence_state(history, msg)
    assert state["query_submitted"] is True
    assert state["result_read_after_query"] is True
    assert state["verified_minimum"] is True
    ctx = pre_llm_call(platform="wechat_desktop", user_message=msg, conversation_history=history)
    assert ctx and "Fresh current-turn query evidence exists" in ctx["context"]


def test_wrong_initial_capture_does_not_poison_later_real_query():
    msg = "OBS0402608230VX order status"
    history = [
        {"role": "user", "content": msg},
        _call("computer_use", '{"action":"capture","app":"Chrome"}'),
        {"role": "tool", "tool_name": "computer_use", "content": "Google Gmail"},
        _call("browser_type", '{"text":"OBS0402608230VX"}'),
        {"role": "tool", "tool_name": "browser_type", "content": "ok"},
        _call("browser_snapshot", '{}'),
        {"role": "tool", "tool_name": "browser_snapshot", "content": "Order OBS0402608230VX status shipped"},
    ]
    state = _evidence_state(history, msg)
    assert state["wrong_page_seen"] is True
    assert state["wrong_page_after_query"] is False
    assert state["verified_minimum"] is True
