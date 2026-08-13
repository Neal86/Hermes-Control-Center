param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$ProgressPreference = "SilentlyContinue"

$DashboardUrl = "http://127.0.0.1:9119"
$PluginProbeUrl = "$DashboardUrl/api/plugins/hermes-extensions/capabilities"
$HostName = "127.0.0.1"
$Port = 9119
$TimeoutSeconds = 30
$HermesHome = if ($env:HERMES_HOME) { $env:HERMES_HOME } elseif ($env:LOCALAPPDATA) { Join-Path $env:LOCALAPPDATA "hermes" } else { Join-Path $HOME ".hermes" }
$env:HERMES_HOME = $HermesHome
$LogDir = Join-Path $HermesHome "logs\control-center"
$StdoutLog = Join-Path $LogDir "dashboard-launch.out.log"
$StderrLog = Join-Path $LogDir "dashboard-launch.err.log"

function Test-LocalPort {
    param([string]$HostName, [int]$Port, [int]$TimeoutMs = 400)
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $async = $client.BeginConnect($HostName, $Port, $null, $null)
        if (-not $async.AsyncWaitHandle.WaitOne($TimeoutMs, $false)) { return $false }
        $client.EndConnect($async)
        return $client.Connected
    } catch { return $false } finally { $client.Close() }
}

function Show-LogTail {
    param([string]$Path, [int]$Lines = 160)
    if (Test-Path -LiteralPath $Path) {
        Write-Host ("--- " + $Path + " ---") -ForegroundColor DarkGray
        Get-Content -LiteralPath $Path -Tail $Lines -ErrorAction SilentlyContinue | Out-Host
    }
}

function Find-Hermes {
    $official = Join-Path $HermesHome "hermes-agent\bin\hermes.exe"
    if (Test-Path -LiteralPath $official) { return $official }
    $cmd = Get-Command hermes -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

function Test-ControlCenterApi {
    try {
        $response = Invoke-WebRequest -Uri $PluginProbeUrl -UseBasicParsing -SkipHttpErrorCheck -TimeoutSec 3
        return [int]$response.StatusCode -ne 404
    } catch {
        return $false
    }
}

function Stop-StaleDashboard {
    param([string]$HermesExe)
    Write-Host "Existing Dashboard has no Control Center API. Restarting it..." -ForegroundColor Yellow
    try { & $HermesExe dashboard --stop 2>&1 | Out-Host } catch {}
    $deadline = (Get-Date).AddSeconds(10)
    while ((Get-Date) -lt $deadline) {
        if (-not (Test-LocalPort -HostName $HostName -Port $Port)) { return }
        Start-Sleep -Milliseconds 300
    }
    throw "Old Dashboard process is still holding port $Port. Close that process and run Setup again."
}

$hermes = Find-Hermes
if (-not $hermes) { throw "Hermes is not installed or its launcher could not be found." }

if (Test-LocalPort -HostName $HostName -Port $Port) {
    if (Test-ControlCenterApi) {
        Write-Host "Hermes Dashboard is already running with Control Center API." -ForegroundColor Green
        Start-Process $DashboardUrl | Out-Null
        Write-Host "Opened $DashboardUrl in the default browser." -ForegroundColor Green
        exit 0
    }
    Stop-StaleDashboard -HermesExe $hermes
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Remove-Item $StdoutLog,$StderrLog -Force -ErrorAction SilentlyContinue

Write-Host "Hermes executable: $hermes"
Write-Host "Starting Hermes Dashboard on $DashboardUrl ..." -ForegroundColor Cyan
$proc = Start-Process -FilePath $hermes -ArgumentList @("dashboard","--skip-build","--no-open","--host",$HostName,"--port",[string]$Port) -PassThru -WindowStyle Hidden -RedirectStandardOutput $StdoutLog -RedirectStandardError $StderrLog
Write-Host ("Dashboard process PID: " + $proc.Id)
Write-Host "Waiting for Dashboard and Control Center API to become ready..."

$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
while ((Get-Date) -lt $deadline) {
    if (Test-LocalPort -HostName $HostName -Port $Port) {
        if (Test-ControlCenterApi) {
            Write-Host "Hermes Dashboard and Control Center API are ready." -ForegroundColor Green
            Start-Process $DashboardUrl | Out-Null
            Write-Host "Opened $DashboardUrl in the default browser." -ForegroundColor Green
            exit 0
        }
    }
    try { $proc.Refresh() } catch {}
    if ($proc.HasExited) {
        Write-Host "Hermes Dashboard exited during startup." -ForegroundColor Red
        Show-LogTail $StdoutLog
        Show-LogTail $StderrLog
        throw "Hermes Dashboard exited before becoming ready (exit code $($proc.ExitCode))."
    }
    Start-Sleep -Milliseconds 500
}

Write-Host "Hermes Dashboard or Control Center API did not become ready within $TimeoutSeconds seconds." -ForegroundColor Red
Show-LogTail $StdoutLog
Show-LogTail $StderrLog
try { if (-not $proc.HasExited) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue } } catch {}
throw "Hermes Dashboard startup timed out or plugin API failed to mount. See the logs shown above."
