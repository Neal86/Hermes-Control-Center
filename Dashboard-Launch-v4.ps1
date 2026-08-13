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

function Find-Hermes {
    $official = Join-Path $HermesHome "hermes-agent\bin\hermes.exe"
    if (Test-Path -LiteralPath $official) { return $official }
    $cmd = Get-Command hermes -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

function Get-PortOwnerPid {
    param([int]$Port)
    try {
        $connections = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop
        $pidValue = @($connections | Select-Object -ExpandProperty OwningProcess -Unique | Where-Object { $_ -gt 0 }) | Select-Object -First 1
        if ($pidValue) { return [int]$pidValue }
    } catch {}
    try {
        $line = netstat -ano -p tcp | Select-String -Pattern (":$Port\s+.*LISTENING\s+(\d+)\s*$") | Select-Object -First 1
        if ($line -and $line.Matches.Count -gt 0) { return [int]$line.Matches[0].Groups[1].Value }
    } catch {}
    return 0
}

function Get-ProcessInfoSafe {
    param([int]$ProcessId)
    try { return Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction Stop } catch { return $null }
}

function Test-IsHermesDashboardProcess {
    param([int]$ProcessId)
    if ($ProcessId -le 0) { return $false }
    $procInfo = Get-ProcessInfoSafe -ProcessId $ProcessId
    if (-not $procInfo) { return $false }
    $name = [string]$procInfo.Name
    $exe = [string]$procInfo.ExecutablePath
    $cmd = [string]$procInfo.CommandLine
    $combined = ($name + " " + $exe + " " + $cmd).ToLowerInvariant()
    $home = $HermesHome.ToLowerInvariant()

    if ($combined.Contains("hermes.exe") -and $combined.Contains("dashboard")) { return $true }
    if ($combined.Contains("hermes-agent") -and $combined.Contains("dashboard")) { return $true }
    if ($combined.Contains($home) -and $combined.Contains("dashboard") -and $combined.Contains("hermes")) { return $true }
    return $false
}

function Get-RunningHermesDashboardPids {
    $result = New-Object System.Collections.Generic.List[int]
    try {
        foreach ($procInfo in Get-CimInstance Win32_Process -ErrorAction Stop) {
            $pidValue = [int]$procInfo.ProcessId
            if ($pidValue -gt 0 -and (Test-IsHermesDashboardProcess -ProcessId $pidValue)) {
                if (-not $result.Contains($pidValue)) { $result.Add($pidValue) }
            }
        }
    } catch {}
    return @($result)
}

function Stop-HermesDashboardPid {
    param([int]$ProcessId)
    if ($ProcessId -le 0) { return }
    $procInfo = Get-ProcessInfoSafe -ProcessId $ProcessId
    if (-not $procInfo) { return }
    if (-not (Test-IsHermesDashboardProcess -ProcessId $ProcessId)) { return }
    Write-Host "Closing Hermes Dashboard process PID $ProcessId..." -ForegroundColor Yellow
    Stop-Process -Id $ProcessId -Force -ErrorAction Stop
}

function Wait-PortFree {
    param([int]$Port, [int]$Seconds = 10)
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        if (-not (Test-LocalPort -Port $Port)) { return $true }
        Start-Sleep -Milliseconds 250
    }
    return -not (Test-LocalPort -Port $Port)
}

function Find-FreePort {
    foreach ($candidate in 9120..9199) {
        if (-not (Test-LocalPort -Port $candidate)) { return $candidate }
    }
    return 0
}

$hermes = Find-Hermes
if (-not $hermes) { throw "Hermes is not installed or its launcher could not be found." }

$Port = $PreferredPort
$preferredInUse = Test-LocalPort -Port $PreferredPort
$preferredOwner = if ($preferredInUse) { Get-PortOwnerPid -Port $PreferredPort } else { 0 }
$preferredIsHermes = $preferredOwner -gt 0 -and (Test-IsHermesDashboardProcess -ProcessId $preferredOwner)

if ($preferredInUse -and (Test-ControlCenterApi -Port $PreferredPort)) {
    Write-Host "Hermes Dashboard is already running with Control Center API on port $PreferredPort." -ForegroundColor Green
    Start-Process "http://127.0.0.1:$PreferredPort/management-center" | Out-Null
    exit 0
}

if ($preferredInUse -and $preferredIsHermes) {
    Write-Host "Port $PreferredPort is held by an old Hermes Dashboard. Restarting it..." -ForegroundColor Yellow
    try { & $hermes dashboard --stop 2>&1 | Out-Host } catch {}
    Start-Sleep -Milliseconds 500
    if (Test-LocalPort -Port $PreferredPort) {
        Stop-HermesDashboardPid -ProcessId $preferredOwner
    }
    if (-not (Wait-PortFree -Port $PreferredPort -Seconds 10)) {
        throw "Old Hermes Dashboard was stopped but port $PreferredPort did not release in time."
    }
}
elseif ($preferredInUse) {
    $runningHermes = @(Get-RunningHermesDashboardPids)
    if ($runningHermes.Count -gt 0) {
        Write-Host "Port $PreferredPort belongs to another application, but Hermes Dashboard process(es) also exist: $($runningHermes -join ', ')." -ForegroundColor Yellow
        foreach ($pidValue in $runningHermes) {
            try {
                Stop-HermesDashboardPid -ProcessId $pidValue
            } catch {
                Write-Host ("Could not close Hermes PID {0}: {1}" -f $pidValue, $_.Exception.Message) -ForegroundColor Yellow
            }
        }
        Start-Sleep -Milliseconds 500
    }

    $Port = Find-FreePort
    if ($Port -eq 0) { throw "Port $PreferredPort is used by another application and no free Dashboard port was found from 9120 through 9199." }
    $owner = Get-ProcessInfoSafe -ProcessId $preferredOwner
    $detail = if ($owner) { (([string]$owner.Name) + " " + ([string]$owner.CommandLine)).Trim() } else { "PID $preferredOwner" }
    Write-Host "Port $PreferredPort is occupied by a non-Hermes process: $detail" -ForegroundColor Yellow
    Write-Host "No usable Hermes Dashboard is running there. Starting Hermes Dashboard on port $Port instead." -ForegroundColor Yellow
}

$DashboardUrl = "http://127.0.0.1:$Port"
$StdoutLog = Join-Path $LogDir ("dashboard-$Port.out.log")
$StderrLog = Join-Path $LogDir ("dashboard-$Port.err.log")
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Remove-Item $StdoutLog,$StderrLog -Force -ErrorAction SilentlyContinue

Write-Host "Hermes executable: $hermes"
Write-Host "Starting fresh Hermes Dashboard on $DashboardUrl ..." -ForegroundColor Cyan
$proc = Start-Process -FilePath $hermes -ArgumentList @("dashboard","--skip-build","--no-open","--host",$HostName,"--port",[string]$Port) -PassThru -WindowStyle Hidden -RedirectStandardOutput $StdoutLog -RedirectStandardError $StderrLog
Write-Host ("Dashboard launcher PID: " + $proc.Id)
Write-Host "Waiting for Dashboard and Control Center API to become ready..."

$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
while ((Get-Date) -lt $deadline) {
    if ((Test-LocalPort -Port $Port) -and (Test-ControlCenterApi -Port $Port)) {
        Write-Host "Hermes Dashboard and Control Center API are ready on port $Port." -ForegroundColor Green
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
