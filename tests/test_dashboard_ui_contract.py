from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "dashboard" / "src"
CORE_JS = "\n".join(
    (SRC / name).read_text("utf-8")
    for name in ("api.js", "components.js", "app.js", "control_center_v2.js", "provider_models_v3.js", "focus_guard.js", "index.js")
)
RESOURCE_JS = (SRC / "resource_selector_v5.js").read_text("utf-8")
CSS = (ROOT / "dashboard" / "dist" / "style.css").read_text("utf-8")
API = "\n".join(
    (ROOT / "dashboard" / name).read_text("utf-8")
    for name in ("plugin_api.py", "plugin_api_v3.py", "plugin_api_v2.py", "extra_api.py")
)
BUILD = (ROOT / "dashboard" / "build_bundle.py").read_text("utf-8")


def test_dashboard_source_has_one_canonical_registration_entry() -> None:
    required = (
        "api.js", "components.js", "app.js", "control_center_v2.js",
        "provider_models_v3.js", "focus_guard.js", "cdp_import_v4.js",
        "resource_selector_v5.js", "canonical_ui.js", "index.js",
    )
    for name in required:
        assert (SRC / name).is_file()
    assert "COMPATIBILITY_ORDER = [" in BUILD
    assert '"resource_selector_v5.js"' in BUILD
    assert 'CANONICAL_ENTRY = "canonical_ui.js"' in BUILD
    assert 'REGISTER_ENTRY = "index.js"' in BUILD
    assert "validate_baseline" in BUILD
    assert 'dist" / "index.js"' in BUILD
    canonical = (SRC / "canonical_ui.js").read_text("utf-8")
    index = (SRC / "index.js").read_text("utf-8")
    assert "CanonicalManagementApp" in canonical
    assert "legacy modules may not replace the main UI" in canonical
    assert "CanonicalManagementApp" in index


def test_management_center_has_complete_tabs_and_states() -> None:
    for tab in ("overview", "agents", "projects", "tasks", "wechat"):
        assert f'"{tab}"' in CORE_JS
    assert "projectSupported" in CORE_JS
    assert "Native Projects unavailable" in CORE_JS
    assert "Loading Management Center" in CORE_JS


def test_agent_project_task_management_surfaces_remain_complete() -> None:
    for token in (
        "Create Agent", "Set default", "Check gateway", "Restart", "Export", "Delete Agent",
        "Create Project", "Use project", "add_folder", "remove_folder", "set_primary", "assign_agent",
        "Create Task", "Run now", "Pause", "Resume", "Delete Task", "Archive Task", "Priority", "Deliver", "Execution history",
    ):
        assert token in CORE_JS


def test_wechat_tab_never_auto_scans_desktop() -> None:
    assert 'if (tab === "wechat") loadHealth(false)' in CORE_JS
    assert 'if (tab === "wechat") loadWeChat(true)' not in CORE_JS
    assert "checkWeChatDesktop" in CORE_JS
    assert "Opening this tab never touches the desktop app" in CORE_JS
    assert "/wechat/status" in CORE_JS
    assert "/wechat/chats?limit=200" in CORE_JS
    assert "/wechat/unread" not in CORE_JS


def test_refresh_is_context_aware_and_auto_refresh_is_visibility_guarded() -> None:
    assert "refreshCurrent" in CORE_JS
    assert 'if (tab === "tasks")' in CORE_JS
    assert 'if (tab === "wechat")' in CORE_JS
    assert 'document.visibilityState !== "visible"' in CORE_JS
    assert "15000" in CORE_JS and "30000" in CORE_JS
    assert "loadHealth(true)" in CORE_JS


def test_dialogs_are_accessible_and_protect_unsaved_changes() -> None:
    assert "focusables" in CORE_JS
    assert 'e.key === "Tab"' in CORE_JS
    assert "previousFocus" in CORE_JS
    assert "Discard unsaved changes?" in CORE_JS
    assert "ConfirmDialog" in CORE_JS
    assert "guardedClose" in CORE_JS
    assert "DIALOG_STACK" in CORE_JS
    assert "closeRef" in CORE_JS
    assert "confirm(" not in CORE_JS


def test_dirty_edits_block_refreshing_lifecycle_actions() -> None:
    assert "Save or discard edits before running lifecycle actions" in CORE_JS
    assert "const blockAction = Boolean(busy) || projectDirty" in CORE_JS
    assert "const blockAction = Boolean(busy) || taskDirty" in CORE_JS
    assert "Boolean(busy) || agentDirty" in CORE_JS


def test_agent_dialog_surfaces_errors_and_loads_provider_fallbacks() -> None:
    assert '"aria-live": "assertive"' in CORE_JS
    assert 'h("strong", null, "Action failed: ")' in CORE_JS
    assert 'request("/providers?profile=default")' in CORE_JS
    assert "mergeProviderData(profileProviders, defaultProviders)" in CORE_JS
    assert "provider.runtime_provider_id || provider.id" in CORE_JS
    assert "Provider/Model choices could not be loaded" in CORE_JS


def test_resource_selector_preserves_browser_choice_and_hides_offline_rows() -> None:
    assert "managed:chrome" in RESOURCE_JS
    assert "managed:edge" in RESOURCE_JS
    assert "iXBrowser" in RESOURCE_JS
    assert 'String(row.status || "").toLowerCase() !== "offline"' in RESOURCE_JS
    assert "Connect / Launch Browser" in RESOURCE_JS


def test_mobile_and_focus_styles_are_touch_friendly() -> None:
    assert "hx-dialog-backdrop" in CSS
    assert "@media(max-width:640px)" in CSS
    assert "min-height:44px" in CSS
    assert ":focus-visible" in CSS
    assert ".hx-actions{flex-wrap:wrap}" in CSS


def test_dashboard_api_exposes_wechat_management_endpoints() -> None:
    for route in ("/wechat/health", "/wechat/status", "/wechat/chats", "/wechat/unread", "/wechat/dry-run"):
        assert route in API
