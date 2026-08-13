param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$ProgressPreference = "SilentlyContinue"

$DashboardUrl = "http://127.0.0.1:9119"
$HostName = "127.0.0.1"
$Port = 9119
$TimeoutSeconds = 30
$HermesHome = if ($env:HERMES_HOME) { $env:HERMES_HOME } elseif ($env:LOCALAPPDATA -and (Test-Path (Join-Path $env:LOCALAPPDATA "hermes"))) { Join-Path $env:LOCALAPPDATA "hermes" } else { Join-Path $HOME ".hermes" }
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

function Show-DashboardLogs {
    Write-Host ""
    Write-Host "Dashboard launch logs:" -ForegroundColor Yellow
    foreach ($path in @($StdoutLog, $StderrLog)) {
        if (Test-Path -LiteralPath $path) {
            Write-Host ("--- " + $path + " ---")
            Get-Content -LiteralPath $path -Tail 80 -ErrorAction SilentlyContinue | Out-Host
        }
    }
}

if (Test-LocalPort -HostName $HostName -Port $Port) {
    Write-Host "Hermes Dashboard is already running on $DashboardUrl." -ForegroundColor Green
    Start-Process $DashboardUrl | Out-Null
    exit 0
}

$hermes = Get-Command hermes -ErrorAction SilentlyContinue
if (-not $hermes) { throw "Hermes is not installed or is not on PATH." }

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Remove-Item -LiteralPath $StdoutLog, $StderrLog -Force -ErrorAction SilentlyContinue

Write-Host "Starting Hermes Dashboard from existing web build..." -ForegroundColor Cyan
$arguments = @("dashboard", "--skip-build", "--no-open", "--host", $HostName, "--port", [string]$Port)

try {
    $proc = Start-Process -FilePath $hermes.Source -ArgumentList $arguments -PassThru -WindowStyle Hidden -RedirectStandardOutput $StdoutLog -RedirectStandardError $StderrLog
} catch {
    throw "Could not start Hermes Dashboard process: $($_.Exception.Message)"
}

Write-Host ("Dashboard process PID: " + $proc.Id)
Write-Host "Waiting for $DashboardUrl ..."
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)

while ((Get-Date) -lt $deadline) {
    if (Test-LocalPort -HostName $HostName -Port $Port) {
        Write-Host "Hermes Dashboard is ready." -ForegroundColor Green
        Start-Process $DashboardUrl | Out-Null
        Write-Host "Opened $DashboardUrl in the default browser."
        exit 0
    }

    try { $proc.Refresh() } catch {}
    if ($proc.HasExited) {
        Show-DashboardLogs
        throw "Hermes Dashboard exited before becoming ready (exit code $($proc.ExitCode))."
    }
    Start-Sleep -Milliseconds 500
}

Show-DashboardLogs
try {
    & $hermes.Source dashboard --status 2>&1 | Out-Host
} catch {}
throw "Hermes Dashboard did not become reachable on $HostName`:$Port within $TimeoutSeconds seconds. See logs above."
