param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$ProgressPreference = "SilentlyContinue"

$DashboardUrl = "http://127.0.0.1:9119"
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

if (Test-LocalPort -HostName $HostName -Port $Port) {
    Write-Host "Hermes Dashboard is already running on $DashboardUrl." -ForegroundColor Green
    Start-Process $DashboardUrl | Out-Null
    Write-Host "Opened $DashboardUrl in the default browser." -ForegroundColor Green
    exit 0
}

$hermes = Find-Hermes
if (-not $hermes) { throw "Hermes is not installed or its launcher could not be found." }

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Remove-Item $StdoutLog,$StderrLog -Force -ErrorAction SilentlyContinue

Write-Host "Hermes executable: $hermes"
Write-Host "Starting Hermes Dashboard on $DashboardUrl ..." -ForegroundColor Cyan
$proc = Start-Process -FilePath $hermes -ArgumentList @("dashboard","--skip-build","--no-open","--host",$HostName,"--port",[string]$Port) -PassThru -WindowStyle Hidden -RedirectStandardOutput $StdoutLog -RedirectStandardError $StderrLog
Write-Host ("Dashboard process PID: " + $proc.Id)
Write-Host "Waiting for Dashboard to become ready..."

$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
while ((Get-Date) -lt $deadline) {
    if (Test-LocalPort -HostName $HostName -Port $Port) {
        Write-Host "Hermes Dashboard is ready." -ForegroundColor Green
        Start-Process $DashboardUrl | Out-Null
        Write-Host "Opened $DashboardUrl in the default browser." -ForegroundColor Green
        exit 0
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

Write-Host "Hermes Dashboard did not become ready within $TimeoutSeconds seconds." -ForegroundColor Red
Show-LogTail $StdoutLog
Show-LogTail $StderrLog
try { if (-not $proc.HasExited) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue } } catch {}
throw "Hermes Dashboard startup timed out. See the logs shown above."
