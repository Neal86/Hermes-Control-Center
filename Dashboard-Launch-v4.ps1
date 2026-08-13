param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$ProgressPreference = "SilentlyContinue"

$HostName = "127.0.0.1"
$Port = 9119
$TimeoutSeconds = 30
$HermesHome = if ($env:HERMES_HOME) { $env:HERMES_HOME } elseif ($env:LOCALAPPDATA) { Join-Path $env:LOCALAPPDATA "hermes" } else { Join-Path $HOME ".hermes" }
$env:HERMES_HOME = $HermesHome
$LogDir = Join-Path $HermesHome "logs\control-center"
$DashboardUrl = "http://127.0.0.1:$Port"
$StdoutLog = Join-Path $LogDir "dashboard-launch.out.log"
$StderrLog = Join-Path $LogDir "dashboard-launch.err.log"

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
    try {
        $url = "$DashboardUrl/api/plugins/hermes-extensions/capabilities"
        $response = Invoke-WebRequest -Uri $url -UseBasicParsing -SkipHttpErrorCheck -TimeoutSec 3
        return [int]$response.StatusCode -ne 404
    } catch { return $false }
}

function Find-Hermes {
    $official = Join-Path $HermesHome "hermes-agent\bin\hermes.exe"
    if (Test-Path -LiteralPath $official) { return $official }
    $cmd = Get-Command hermes -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

function Get-PortOwnerPid {
    try {
        $connections = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop
        $pid = @($connections | Select-Object -ExpandProperty OwningProcess -Unique | Where-Object { $_ -gt 0 }) | Select-Object -First 1
        if ($pid) { return [int]$pid }
    } catch {}
    try {
        $line = netstat -ano -p tcp | Select-String -Pattern (":$Port\s+.*LISTENING\s+(\d+)\s*$") | Select-Object -First 1
        if ($line -and $line.Matches.Count -gt 0) { return [int]$line.Matches[0].Groups[1].Value }
    } catch {}
    return 0
}

function Test-IsHermesDashboardProcess {
    param([int]$ProcessId)
    if ($ProcessId -le 0) { return $false }
    try {
        $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction Stop
        $name = [string]$proc.Name
        $exe = [string]$proc.ExecutablePath
        $cmd = [string]$proc.CommandLine
        $combined = ($name + " " + $exe + " " + $cmd).ToLowerInvariant()
        $home = $HermesHome.ToLowerInvariant()
        if ($combined.Contains($home) -and ($combined.Contains("dashboard") -or $combined.Contains("hermes"))) { return $true }
        if ($combined.Contains("hermes-agent") -and ($combined.Contains("dashboard") -or $combined.Contains("9119"))) { return $true }
        if ($combined.Contains("hermes.exe") -and $combined.Contains("dashboard")) { return $true }
    } catch {}
    return $false
}

function Stop-StaleHermesDashboard {
    param([string]$HermesExe)
    Write-Host "Stopping stale Hermes Dashboard on port $Port..." -ForegroundColor Yellow
    try { & $HermesExe dashboard --stop 2>&1 | Out-Host } catch {}
    Start-Sleep -Milliseconds 800
    if (-not (Test-LocalPort -Port $Port)) { return }

    $ownerPid = Get-PortOwnerPid
    if ($ownerPid -le 0) { throw "Port $Port is still in use, but its owner PID could not be determined." }
    if (-not (Test-IsHermesDashboardProcess -ProcessId $ownerPid)) {
        try {
            $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$ownerPid" -ErrorAction Stop
            $detail = ([string]$proc.Name + " " + [string]$proc.CommandLine).Trim()
        } catch { $detail = "PID $ownerPid" }
        throw "Port $Port is held by a non-Hermes process: $detail"
    }

    Write-Host "Closing stale Hermes Dashboard process PID $ownerPid..." -ForegroundColor Yellow
    Stop-Process -Id $ownerPid -Force -ErrorAction Stop
    $deadline = (Get-Date).AddSeconds(10)
    while ((Get-Date) -lt $deadline) {
        if (-not (Test-LocalPort -Port $Port)) {
            Write-Host "Port $Port released." -ForegroundColor Green
            return
        }
        Start-Sleep -Milliseconds 250
    }
    throw "Stale Hermes Dashboard PID $ownerPid was stopped, but port $Port did not release in time."
}

$hermes = Find-Hermes
if (-not $hermes) { throw "Hermes is not installed or its launcher could not be found." }

if (Test-LocalPort -Port $Port) {
    if (Test-ControlCenterApi) {
        Write-Host "Hermes Dashboard is already running with Control Center API." -ForegroundColor Green
        Start-Process $DashboardUrl | Out-Null
        exit 0
    }
    Stop-StaleHermesDashboard -HermesExe $hermes
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Remove-Item $StdoutLog,$StderrLog -Force -ErrorAction SilentlyContinue

Write-Host "Hermes executable: $hermes"
Write-Host "Starting fresh Hermes Dashboard on $DashboardUrl ..." -ForegroundColor Cyan
$proc = Start-Process -FilePath $hermes -ArgumentList @("dashboard","--skip-build","--no-open","--host",$HostName,"--port",[string]$Port) -PassThru -WindowStyle Hidden -RedirectStandardOutput $StdoutLog -RedirectStandardError $StderrLog
Write-Host ("Dashboard process PID: " + $proc.Id)
Write-Host "Waiting for Dashboard and Control Center API to become ready..."

$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
while ((Get-Date) -lt $deadline) {
    if ((Test-LocalPort -Port $Port) -and (Test-ControlCenterApi)) {
        Write-Host "Hermes Dashboard and Control Center API are ready." -ForegroundColor Green
        Start-Process "$DashboardUrl/management-center" | Out-Null
        Write-Host "Opened $DashboardUrl/management-center" -ForegroundColor Green
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
try { if (-not $proc.HasExited) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue } } catch {}
throw "Hermes Dashboard started on $DashboardUrl but Control Center API did not become ready within $TimeoutSeconds seconds."
