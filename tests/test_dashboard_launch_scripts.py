from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = (ROOT / "Dashboard-Launch-v4.ps1").read_text("utf-8")
LOOP_V8 = (ROOT / "Setup-Loop-v8.ps1").read_text("utf-8")
CORE_SETUP = (ROOT / "Setup-Hermes-Control-Center.ps1").read_text("utf-8")


def test_dashboard_launcher_waits_long_enough_for_server_readiness() -> None:
    assert '$TimeoutSeconds = 90' in DASHBOARD


def test_dashboard_launcher_resolves_official_home_bin_first() -> None:
    assert '(Join-Path $HermesHome "bin\\hermes.exe")' in DASHBOARD
    assert '(Join-Path $HermesHome "hermes-agent\\bin\\hermes.exe")' in DASHBOARD


def test_dashboard_launcher_bootstraps_a_missing_web_dist() -> None:
    assert 'function Ensure-DashboardWebBuild' in DASHBOARD
    assert 'npm install --include=dev --workspace web' in DASHBOARD
    assert 'npm run build -w web' in DASHBOARD
    assert 'hermes_cli\\web_dist\\index.html' in DASHBOARD
    assert 'Ensure-DashboardWebBuild -AgentRoot $hermesAgentRoot' in DASHBOARD


def test_dashboard_launcher_can_install_private_node_without_admin_rights() -> None:
    assert 'https://nodejs.org/dist/latest-v22.x' in DASHBOARD
    assert 'SHASUMS256.txt' in DASHBOARD
    assert 'Get-FileHash -LiteralPath $zip -Algorithm SHA256' in DASHBOARD
    assert 'runtime\\node\\npm.cmd' in DASHBOARD


def test_existing_web_dist_keeps_the_fast_skip_build_path() -> None:
    assert 'if (Test-Path -LiteralPath $webDistIndex)' in DASHBOARD
    assert '@("dashboard","--skip-build","--no-open"' in DASHBOARD


def test_core_setup_uses_verified_v4_launcher_for_open_and_restart() -> None:
    assert '$DashboardLauncher = Join-Path $Root "Dashboard-Launch-v4.ps1"' in CORE_SETUP
    assert '-PreferredPort $Port -NoOpen' in CORE_SETUP


def test_setup_menu_waits_for_real_dashboard_result() -> None:
    assert 'Start-Process -FilePath "powershell.exe" -ArgumentList $args -Wait -PassThru' in LOOP_V8
    assert 'return [int]$proc.ExitCode' in LOOP_V8
    assert 'Hermes Dashboard opened successfully.' in LOOP_V8
    assert 'Dashboard launch started in background' not in LOOP_V8
