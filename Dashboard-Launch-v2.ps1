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
$WebInstallOut = Join-Path $LogDir "dashboard-web-install.out.log"
$WebInstallErr = Join-Path $LogDir "dashboard-web-install.err.log"
$WebBuildOut = Join-Path $LogDir "dashboard-web-build.out.log"
$WebBuildErr = Join-Path $LogDir "dashboard-web-build.err.log"

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

function Find-NpmCommand {
    $npmCmd = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if ($npmCmd) { return $npmCmd.Source }
    $npm = Get-Command npm -ErrorAction SilentlyContinue
    if ($npm) { return $npm.Source }
    return $null
}

function Convert-NpmVersion {
    param([string]$VersionText)
    if ($VersionText -match '([0-9]+)\.([0-9]+)\.([0-9]+)') {
        return [version]::new([int]$Matches[1], [int]$Matches[2], [int]$Matches[3])
    }
    return $null
}

function Ensure-CompatibleNpm {
    $npm = Find-NpmCommand
    if (-not $npm) { throw "Node/npm is not available." }
    $versionText = (& $npm --version | Out-String).Trim()
    $version = Convert-NpmVersion $versionText
    if ($null -eq $version) { throw "Could not determine npm version from '$versionText'." }

    $badFloor = [version]"11.10.0"
    $goodFloor = [version]"11.17.0"
    if ($version -ge $badFloor -and $version -lt $goodFloor) {
        Write-Host "npm $versionText is incompatible with Hermes' security policy. Upgrading npm to 11.17+..." -ForegroundColor Yellow
        $upgradeOut = Join-Path $LogDir "npm-upgrade.out.log"
        $upgradeErr = Join-Path $LogDir "npm-upgrade.err.log"
        Remove-Item $upgradeOut,$upgradeErr -Force -ErrorAction SilentlyContinue
        $p = Start-Process -FilePath $npm -ArgumentList @("install","-g","npm@^11.17.0") -Wait -PassThru -NoNewWindow -RedirectStandardOutput $upgradeOut -RedirectStandardError $upgradeErr
        Show-LogTail $upgradeOut 80
        Show-LogTail $upgradeErr 80
        if ($p.ExitCode -ne 0) { throw "Automatic npm upgrade failed with exit code $($p.ExitCode)." }
        $npm = Find-NpmCommand
        $versionText = (& $npm --version | Out-String).Trim()
        $version = Convert-NpmVersion $versionText
        if ($null -eq $version -or $version -lt $goodFloor) { throw "Compatible npm >=11.17.0 was not found after upgrade." }
        Write-Host "npm upgraded successfully to $versionText." -ForegroundColor Green
    }
    return $npm
}

function Invoke-NpmStep {
    param(
        [string]$Npm,
        [string[]]$Arguments,
        [string]$Stdout,
        [string]$Stderr,
        [string]$Label
    )
    Remove-Item $Stdout,$Stderr -Force -ErrorAction SilentlyContinue
    Write-Host $Label -ForegroundColor Cyan
    $proc = Start-Process -FilePath $Npm -ArgumentList $Arguments -WorkingDirectory $HermesRoot -Wait -PassThru -NoNewWindow -RedirectStandardOutput $Stdout -RedirectStandardError $Stderr
    Show-LogTail $Stdout 120
    Show-LogTail $Stderr 120
    if ($proc.ExitCode -ne 0) { throw "$Label failed with exit code $($proc.ExitCode)." }
}

function Repair-HermesWebDist {
    if (Test-Path -LiteralPath $WebIndex) {
        Write-Host "Hermes web dist already exists." -ForegroundColor Green
        return
    }
    if (-not (Test-Path -LiteralPath (Join-Path $HermesRoot "package.json"))) { throw "Hermes source root was not found at '$HermesRoot'." }
    if (-not (Test-Path -LiteralPath (Join-Path $HermesRoot "web\package.json"))) { throw "Hermes web workspace is missing." }

    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
    $npm = Ensure-CompatibleNpm
    $nodeVersion = (& node --version | Out-String).Trim()
    $npmVersion = (& $npm --version | Out-String).Trim()
    Write-Host "Hermes Dashboard web dist is missing. Repairing it now..." -ForegroundColor Cyan
    Write-Host "Node: $nodeVersion   npm: $npmVersion"

    Invoke-NpmStep -Npm $npm -Arguments @("install","--workspace","web") -Stdout $WebInstallOut -Stderr $WebInstallErr -Label "Installing Hermes web dependencies"
    Invoke-NpmStep -Npm $npm -Arguments @("run","build","--workspace","web") -Stdout $WebBuildOut -Stderr $WebBuildErr -Label "Building Hermes web UI"

    if (-not (Test-Path -LiteralPath $WebIndex)) {
        throw "Hermes web build exited successfully but did not produce '$WebIndex'."
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
Remove-Item $StdoutLog,$StderrLog -Force -ErrorAction SilentlyContinue

Write-Host "Starting Hermes Dashboard from existing web build..." -ForegroundColor Cyan
$proc = Start-Process -FilePath $hermes.Source -ArgumentList @("dashboard","--skip-build","--no-open","--host",$HostName,"--port",[string]$Port) -PassThru -WindowStyle Hidden -RedirectStandardOutput $StdoutLog -RedirectStandardError $StderrLog
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
        Show-LogTail $StdoutLog 120
        Show-LogTail $StderrLog 120
        throw "Hermes Dashboard exited before becoming ready (exit code $($proc.ExitCode))."
    }
    Start-Sleep -Milliseconds 500
}
Show-LogTail $StdoutLog 120
Show-LogTail $StderrLog 120
throw "Hermes Dashboard did not become reachable within $TimeoutSeconds seconds."
