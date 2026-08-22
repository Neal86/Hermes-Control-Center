"""Backward-compatible browser runtime facade.

Browser-specific implementation now lives in browser.runtime. Existing Dashboard
and discovery imports may continue using resources.browser_manager during the
compatibility window without creating a second implementation.
"""

from browser.runtime import (  # noqa: F401
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
