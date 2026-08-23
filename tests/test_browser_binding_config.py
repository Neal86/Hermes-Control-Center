from pathlib import Path


def test_bound_cdp_browser_forces_builtin_backend_before_restart():
    source = (Path(__file__).resolve().parents[1] / "dashboard" / "extra_api.py").read_text(encoding="utf-8")
    backend = 'management._set_config(agent, "browser.backend", "off")'
    cdp = 'management._set_config(agent, "browser.cdp_url", cdp_url)'
    restart = 'management.agent_action(agent, "gateway_restart")'
    assert backend in source
    assert cdp in source
    assert source.index(backend) < source.index(cdp) < source.index(restart, source.index(cdp))
