from resources.bindings import ResourceAccessError
from wechat.binding import WeChatBindingService


def _service(tmp_path, resources, *, remember=True):
    service = WeChatBindingService(tmp_path)
    service.bindings._write({"wechat:old": "11"})
    service.bindings.registry.refresh = lambda: resources
    service.bindings.registry.list = lambda refresh=False: resources
    if remember:
        service._remember(
            "11",
            {
                "id": "wechat:old",
                "kind": "wechat",
                "app": "wechat",
                "exe": "c:/wechat/wechat.exe",
                "title": "WeChat",
                "online": False,
                "status": "offline",
            },
        )
    return service


def _row(resource_id, *, online, status="ready"):
    return {
        "id": resource_id,
        "kind": "wechat",
        "app": "wechat",
        "exe": "c:/wechat/wechat.exe",
        "title": "WeChat",
        "online": online,
        "status": status,
    }


def test_require_recovers_unique_compatible_live_replacement(tmp_path):
    resources = [
        _row("wechat:old", online=False, status="offline"),
        _row("wechat:new", online=True),
    ]
    service = _service(tmp_path, resources)

    resource = service.require("11", ready=True)

    assert resource["id"] == "wechat:new"
    assert resource["rebound_from"] == "wechat:old"
    assert service.bindings.list() == {"wechat:new": "11"}


def test_unique_legacy_binding_is_migrated_without_pid_or_hwnd_guessing(tmp_path):
    resources = [
        _row("wechat:old", online=False, status="offline"),
        _row("wechat:new", online=True),
    ]
    service = _service(tmp_path, resources, remember=False)

    resource = service.require("11", ready=True)

    assert resource["id"] == "wechat:new"
    assert resource["rebound_from"] == "wechat:old"
    records = service._read()
    assert len(records) == 1
    record = next(iter(records.values()))
    assert record["runtime_resource_id"] == "wechat:new"
    assert record["needs_rebind"] is False


def test_require_does_not_guess_between_multiple_live_replacements(tmp_path):
    resources = [
        _row("wechat:old", online=False, status="offline"),
        _row("wechat:a", online=True),
        _row("wechat:b", online=True),
    ]
    service = _service(tmp_path, resources)

    try:
        service.require("11", ready=True)
    except ResourceAccessError as exc:
        assert "found 2 compatible unbound live replacement(s)" in str(exc)
    else:
        raise AssertionError("ambiguous replacement must fail closed")

    assert service.bindings.list() == {"wechat:old": "11"}


def test_legacy_binding_also_fails_closed_between_multiple_replacements(tmp_path):
    resources = [
        _row("wechat:old", online=False, status="offline"),
        _row("wechat:a", online=True),
        _row("wechat:b", online=True),
    ]
    service = _service(tmp_path, resources, remember=False)

    try:
        service.require("11", ready=True)
    except ResourceAccessError as exc:
        assert "found 2 compatible unbound live replacement(s)" in str(exc)
    else:
        raise AssertionError("ambiguous legacy replacement must fail closed")

    assert service.bindings.list() == {"wechat:old": "11"}


def test_require_does_not_resurrect_explicitly_unbound_wechat(tmp_path):
    resources = [
        _row("wechat:old", online=False, status="offline"),
        _row("wechat:new", online=True),
    ]
    service = _service(tmp_path, resources)
    service.bindings.unbind("wechat:old")

    try:
        service.require("11", ready=True)
    except ResourceAccessError:
        pass
    else:
        raise AssertionError("explicit unbind must not recover automatically")

    assert service.bindings.list() == {}
