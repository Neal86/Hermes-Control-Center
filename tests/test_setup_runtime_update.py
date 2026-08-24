from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SETUP = (ROOT / "Setup-Hermes-Control-Center.ps1").read_text("utf-8")


def test_hermes_update_stops_dashboard_before_updating_runtime() -> None:
    required = (
        "Get-RunningHermesDashboardPort",
        "$hermesHomeLower = ([string]$HermesHome).ToLowerInvariant()",
        "Wait-HermesDashboardStopped",
        "dashboard --stop",
        "Hermes Dashboard did not stop cleanly before runtime update",
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