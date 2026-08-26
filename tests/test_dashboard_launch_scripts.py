from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = (ROOT / "Dashboard-Launch-v4.ps1").read_text("utf-8")
LOOP_V8 = (ROOT / "Setup-Loop-v8.ps1").read_text("utf-8")


def test_dashboard_launcher_waits_long_enough_for_cold_windows_startup() -> None:
    assert '$TimeoutSeconds = 90' in DASHBOARD


def test_dashboard_launcher_resolves_official_home_bin_first() -> None:
    assert '(Join-Path $HermesHome "bin\\hermes.exe")' in DASHBOARD
    assert '(Join-Path $HermesHome "hermes-agent\\bin\\hermes.exe")' in DASHBOARD


def test_setup_menu_waits_for_real_dashboard_result() -> None:
    assert 'Start-Process -FilePath "powershell.exe" -ArgumentList $args -Wait -PassThru' in LOOP_V8
    assert 'return [int]$proc.ExitCode' in LOOP_V8
    assert 'Hermes Dashboard opened successfully.' in LOOP_V8
    assert 'Dashboard launch started in background' not in LOOP_V8
