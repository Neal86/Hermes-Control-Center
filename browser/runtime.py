from __future__ import annotations

# The implementation remains imported from the compatibility facade during the
# migration so existing Dashboard/API imports and installed-state upgrades keep
# working. New domain code should import browser.runtime, not resources.browser_manager.
from resources.browser_manager import (  # noqa: F401
    browser_diagnostic_log_path,
    default_user_data_dir,
    find_browser_executable,
    import_existing_browser_to_cdp,
    launch_managed_browser,
    log_browser_event,
    managed_profile_dir,
    probe_cdp,
)

__all__ = [
    "browser_diagnostic_log_path",
    "default_user_data_dir",
    "find_browser_executable",
    "import_existing_browser_to_cdp",
    "launch_managed_browser",
    "log_browser_event",
    "managed_profile_dir",
    "probe_cdp",
]
