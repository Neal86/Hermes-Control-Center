param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$ProgressPreference = "SilentlyContinue"

$HostName = "127.0.0.1"
$PreferredPort = 9119
$TimeoutSeconds = 30
$HermesHome = if ($env:HERMES_HOME) { $env:HERMES_HOME } elseif ($env:LOCALAPPDATA) { Join-Path $env:LOCALAPPDATA "hermes" } else { Join-Path $HOME ".hermes" }
$env:HERMES_HOME = $HermesHome
$LogDir = Join-Path $HermesHome "logs\control-center"

function Test-LocalPort {
    param([int]$Port, [int]$TimeoutMs = 400)
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $async = $client.BeginConnect($HostName, $Port, $null, $null)
        if (-not $async.AsyncWaitHandle.WaitOne($TimeoutMs, $false)) { return $false }
        $client.EndConnect($async)
        return $client.Connected
    } catch { return $false } finally { $client.Close() }
}

function Test-ControlCenterApi {
    param([int]$Port)
    try {
        $url = "http://127.0.0.1:$Port/api/plugins/hermes-extensions/capabilities"
        $response = Invoke-WebRequest -Uri $url -UseBasicParsing -SkipHttpErrorCheck -TimeoutSec 3
        return [int]$response.StatusCode -ne 404
    } catch { return $false }
}

function Find-FreePort {
    foreach ($candidate in 9120..9130) {
        if (-not (Test-LocalPort -Port $candidate)) { return $candidate }
    }
    return 0
}

function Find-Hermes {
    $official = Join-Path $HermesHome "hermes-agent\bin\hermes.exe"
    if (Test-Path -LiteralPath $official) { return $official }
    $cmd = Get-Command hermes -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

$hermes = Find-Hermes
if (-not $hermes) { throw "Hermes is not installed or its launcher could not be found." }

$Port = $PreferredPort
if (Test-LocalPort -Port $PreferredPort) {
    if (Test-ControlCenterApi -Port $PreferredPort) {
        $url = "http://127.0.0.1:$PreferredPort"
        Write-Host "Hermes Dashboard is already running with Control Center API." -ForegroundColor Green
        Start-Process $url | Out-Null
        exit 0
    }
    $Port = Find-FreePort
    if ($Port -eq 0) { throw "Port 9119 is stale and no free Dashboard port was found from 9120 through 9130." }
    Write-Host "Port 9119 is owned by a stale Dashboard process. Starting a clean Dashboard on port $Port instead." -ForegroundColor Yellow
}

$DashboardUrl = "http://127.0.0.1:$Port"
$StdoutLog = Join-Path $LogDir ("dashboard-$Port.out.log")
$StderrLog = Join-Path $LogDir ("dashboard-$Port.err.log")
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Remove-Item $StdoutLog,$StderrLog -Force -ErrorAction SilentlyContinue

Write-Host "Hermes executable: $hermes"
Write-Host "Starting Hermes Dashboard on $DashboardUrl ..." -ForegroundColor Cyan
$proc = Start-Process -FilePath $hermes -ArgumentList @("dashboard","--skip-build","--no-open","--host",$HostName,"--port",[string]$Port) -PassThru -WindowStyle Hidden -RedirectStandardOutput $StdoutLog -RedirectStandardError $StderrLog
Write-Host ("Dashboard process PID: " + $proc.Id)
Write-Host "Waiting for Dashboard and Control Center API to become ready..."

$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
while ((Get-Date) -lt $deadline) {
    if ((Test-LocalPort -Port $Port) -and (Test-ControlCenterApi -Port $Port)) {
        Write-Host "Hermes Dashboard and Control Center API are ready." -ForegroundColor Green
        Start-Process $DashboardUrl | Out-Null
        Write-Host "Opened $DashboardUrl in the default browser." -ForegroundColor Green
        exit 0
    }
    try { $proc.Refresh() } catch {}
    if ($proc.HasExited) {
        if (Test-Path $StdoutLog) { Get-Content $StdoutLog -Tail 160 | Out-Host }
        if (Test-Path $StderrLog) { Get-Content $StderrLog -Tail 160 | Out-Host }
        throw "Hermes Dashboard exited before Control Center API became ready."
    }
    Start-Sleep -Milliseconds 500
}

if (Test-Path $StdoutLog) { Get-Content $StdoutLog -Tail 160 | Out-Host }
if (Test-Path $StderrLog) { Get-Content $StderrLog -Tail 160 | Out-Host }
throw "Hermes Dashboard started on $DashboardUrl but Control Center API did not become ready within $TimeoutSeconds seconds."
