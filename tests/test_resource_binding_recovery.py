from resources.bindings import ResourceAccessError, ResourceBindings


def _bindings(tmp_path, resources):
    bindings = ResourceBindings(tmp_path)
    bindings._write({"wechat:old": "11"})
    bindings.registry.refresh = lambda: resources
    bindings.registry.list = lambda refresh=False: resources
    return bindings


def test_require_recovers_unique_live_replacement(tmp_path):
    resources = [
        {"id": "wechat:old", "kind": "wechat", "online": False, "status": "offline"},
        {"id": "wechat:new", "kind": "wechat", "online": True, "status": "ready"},
    ]
    bindings = _bindings(tmp_path, resources)

    resource = bindings.require("11", "wechat", ready=True)

    assert resource["id"] == "wechat:new"
    assert resource["rebound_from"] == "wechat:old"
    assert bindings.list() == {"wechat:new": "11"}


def test_require_does_not_guess_between_multiple_live_replacements(tmp_path):
    resources = [
        {"id": "wechat:old", "kind": "wechat", "online": False, "status": "offline"},
        {"id": "wechat:a", "kind": "wechat", "online": True, "status": "ready"},
        {"id": "wechat:b", "kind": "wechat", "online": True, "status": "ready"},
    ]
    bindings = _bindings(tmp_path, resources)

    try:
        bindings.require("11", "wechat", ready=True)
    except ResourceAccessError as exc:
        assert "found 2 unbound live replacement(s)" in str(exc)
    else:
        raise AssertionError("ambiguous replacement must fail closed")

    assert bindings.list() == {"wechat:old": "11"}
