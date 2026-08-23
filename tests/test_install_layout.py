from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = (ROOT / "install.ps1").read_text("utf-8")


def test_installer_copies_final_domain_packages() -> None:
    for required in (
        '"gateway_isolation.py"',
        '"browser"',
        '"hcc_gateway"',
        '"wechat\\binding.py"',
        '"wechat\\receiver.py"',
        '"wechat\\sender.py"',
        '"wechat\\state.py"',
        '"browser\\runtime.py"',
        '"hcc_gateway\\lifecycle.py"',
    ):
        assert required in INSTALLER, required


def test_installer_staging_validation_covers_gateway_and_wechat_domains() -> None:
    for required in (
        '"gateway_isolation.py"',
        '"wechat\\binding.py"',
        '"wechat\\receiver.py"',
        '"hcc_gateway\\routing.py"',
    ):
        assert INSTALLER.count(required) >= 2, required


def test_installer_refreshes_and_reloads_running_control_center_runtime() -> None:
    for required in (
        "Refresh-IsolatedProfileRuntime",
        "_persist_independent_gateway_config",
        "_sync_enabled_user_plugins",
        "Get-RunningGatewayProfiles",
        "Get-RunningDashboardPort",
        "gateway restart",
        "dashboard --stop",
    ):
        assert required in INSTALLER, required


def test_installer_supports_json_and_legacy_gateway_pid_files() -> None:
    for required in (
        "Read-GatewayPid",
        "ConvertFrom-Json",
        "payload.pid",
        "[int]::TryParse($raw",
    ):
        assert required in INSTALLER, required


def test_installer_verifies_gateway_restart_with_a_new_live_pid() -> None:
    for required in (
        "$beforePid = Read-GatewayPid",
        "$afterPid = Read-GatewayPid",
        "$afterPid -ne $beforePid",
        "Get-Process -Id $afterPid",
        "Gateway restart verification failed",
    ):
        assert required in INSTALLER, required
