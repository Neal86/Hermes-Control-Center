from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SETUP = (ROOT / "Setup-Hermes-Control-Center.ps1").read_text("utf-8")


def test_hermes_update_stops_only_dashboard_runtime_before_update() -> None:
    required = (
        "Get-RunningHermesDashboardProcesses",
        "$hermesHomeLower = ([string]$HermesHome).ToLowerInvariant()",
        "Stop-HermesDashboardForUpdate",
        "dashboard --stop",
        "Stop-Process -Id ([int]$proc.ProcessId) -Force",
        "Wait-HermesDashboardStopped",
        "& (Get-HermesCommand).Source update",
    )
    for item in required:
        assert item in SETUP, item
    assert "$home =" not in SETUP


def test_hermes_update_restores_previously_running_dashboard() -> None:
    assert "$dashboardWasRunning = $dashboardPort -gt 0" in SETUP
    assert "finally {" in SETUP
    assert "Start-HermesDashboardAfterUpdate -Port $dashboardPort" in SETUP
    assert '"dashboard","--skip-build","--no-open","--host","127.0.0.1","--port"' in SETUP


def test_dashboard_force_stop_is_scoped_to_detected_dashboard_processes() -> None:
    assert 'combined.Contains("dashboard")' in SETUP
    assert 'combined.Contains("hermes")' in SETUP
    assert 'combined.Contains($hermesHomeLower)' in SETUP
    assert "Get-Process | Stop-Process" not in SETUP

def test_hermes_update_defers_optional_cua_refresh_without_changing_final_setting() -> None:
    assert "Get-HermesCuaRefreshSetting" in SETUP
    assert 'Set-HermesCuaRefreshSetting -Value "false"' in SETUP
    assert 'Set-HermesCuaRefreshSetting -Value $cuaRefreshSetting' in SETUP
    assert "Deferring optional cua-driver refresh until after the core Hermes update" in SETUP


def test_hermes_update_restores_previously_running_gateway_profiles() -> None:
    assert "Get-RunningHermesGatewayProfilesForUpdate" in SETUP
    assert "Ensure-HermesGatewayProfilesAfterUpdate -Profiles $gatewayProfiles" in SETUP
    assert "gateway start" in SETUP
    assert "Gateway process running" in SETUP

def test_hermes_update_accepts_nonzero_exit_only_after_verified_success() -> None:
    assert "$updateExitCode = $LASTEXITCODE" in SETUP
    assert "$installedAfterUpdate = Get-HermesInstalledVersion" in SETUP
    assert "$runtimeStillNeedsUpdate = Test-HermesRuntimeNeedsUpdate" in SETUP
    assert "$installedAfterUpdate -eq $latest -and -not $runtimeStillNeedsUpdate" in SETUP
    assert "verified runtime is current, continuing" in SETUP
    assert 'throw "Hermes runtime update exited with code $updateExitCode."' in SETUP