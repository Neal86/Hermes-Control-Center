param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$ProgressPreference = "SilentlyContinue"

$DashboardUrl = "http://127.0.0.1:9119"
$HostName = "127.0.0.1"
$Port = 9119
$TimeoutSeconds = 30
$HermesHome = if ($env:HERMES_HOME) { $env:HERMES_HOME } elseif ($env:LOCALAPPDATA -and (Test-Path (Join-Path $env:LOCALAPPDATA "hermes"))) { Join-Path $env:LOCALAPPDATA "hermes" } else { Join-Path $HOME ".hermes" }
$HermesRoot = Join-Path $HermesHome "hermes-agent"
$WebDist = Join-Path $HermesRoot "hermes_cli\web_dist"
$WebIndex = Join-Path $WebDist "index.html"
$LogDir = Join-Path $HermesHome "logs\control-center"
$StdoutLog = Join-Path $LogDir "dashboard-launch.out.log"
$StderrLog = Join-Path $LogDir "dashboard-launch.err.log"
$WebBuildLog = Join-Path $LogDir "dashboard-web-build.log"

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
    param([string]$Path, [int]$Lines = 120)
    if (Test-Path -LiteralPath $Path) {
        Write-Host ("--- " + $Path + " ---")
        Get-Content -LiteralPath $Path -Tail $Lines -ErrorAction SilentlyContinue | Out-Host
    }
}

function Show-DashboardLogs {
    Write-Host ""
    Write-Host "Dashboard launch logs:" -ForegroundColor Yellow
    Show-LogTail $StdoutLog 80
    Show-LogTail $StderrLog 80
}

function Find-NpmCommand {
    $npmCmd = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if ($npmCmd) { return $npmCmd.Source }
    $npm = Get-Command npm -ErrorAction SilentlyContinue
    if ($npm) { return $npm.Source }
    return $null
}

function Repair-HermesWebDist {
    if (Test-Path -LiteralPath $WebIndex) {
        Write-Host "Hermes web dist already exists." -ForegroundColor Green
        return
    }

    if (-not (Test-Path -LiteralPath (Join-Path $HermesRoot "package.json"))) {
        throw "Hermes source root was not found at '$HermesRoot'. Cannot build Dashboard web assets."
    }
    if (-not (Test-Path -LiteralPath (Join-Path $HermesRoot "web\package.json"))) {
        throw "Hermes web workspace is missing under '$HermesRoot\web'."
    }

    $npm = Find-NpmCommand
    if (-not $npm) {
        throw "Node/npm is not available. Hermes Dashboard web assets are missing and cannot be rebuilt automatically."
    }

    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
    Remove-Item -LiteralPath $WebBuildLog -Force -ErrorAction SilentlyContinue

    $nodeVersion = try { (& node --version 2>&1 | Out-String).Trim() } catch { "unknown" }
    $npmVersion = try { (& $npm --version 2>&1 | Out-String).Trim() } catch { "unknown" }
    Write-Host "Hermes Dashboard web dist is missing. Repairing it now..." -ForegroundColor Cyan
    Write-Host "Node: $nodeVersion   npm: $npmVersion"
    Write-Host "Web build log: $WebBuildLog"

    Push-Location $HermesRoot
    try {
        "=== npm install --workspace web ===" | Out-File -LiteralPath $WebBuildLog -Encoding utf8
        & $npm install --workspace web 2>&1 | Tee-Object -FilePath $WebBuildLog -Append | Out-Host
        $installCode = $LASTEXITCODE
        if ($installCode -ne 0) {
            Write-Host ""
            Write-Host "Hermes web dependency installation failed." -ForegroundColor Red
            Show-LogTail $WebBuildLog 160
            throw "npm install --workspace web failed with exit code $installCode."
        }

        "`n=== npm run build --workspace web ===" | Out-File -LiteralPath $WebBuildLog -Append -Encoding utf8
        & $npm run build --workspace web 2>&1 | Tee-Object -FilePath $WebBuildLog -Append | Out-Host
        $buildCode = $LASTEXITCODE
        if ($buildCode -ne 0) {
            Write-Host ""
            Write-Host "Hermes web build failed." -ForegroundColor Red
            Show-LogTail $WebBuildLog 160
            throw "npm run build --workspace web failed with exit code $buildCode."
        }
    } finally {
        Pop-Location
    }

    if (-not (Test-Path -LiteralPath $WebIndex)) {
        Show-LogTail $WebBuildLog 160
        throw "Hermes web build completed without producing '$WebIndex'."
    }

    Write-Host "Hermes Dashboard web assets repaired successfully." -ForegroundColor Green
}

if (Test-LocalPort -HostName $HostName -Port $Port) {
    Write-Host "Hermes Dashboard is already running on $DashboardUrl." -ForegroundColor Green
    Start-Process $DashboardUrl | Out-Null
    exit 0
}

$hermes = Get-Command hermes -ErrorAction SilentlyContinue
if (-not $hermes) { throw "Hermes is not installed or is not on PATH." }

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Repair-HermesWebDist
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
