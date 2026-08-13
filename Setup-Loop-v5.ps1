param()

$ErrorActionPreference = "Continue"
Set-StrictMode -Version Latest
$ProgressPreference = "SilentlyContinue"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$CoreSetup = Join-Path $Root "Setup-Hermes-Control-Center.ps1"
$SafeInstaller = Join-Path $Root "Install-Control-Center-Safe.ps1"
$Dashboard = Join-Path $Root "Dashboard-Launch-v3.ps1"
$HermesHome = if ($env:HERMES_HOME) { $env:HERMES_HOME } elseif ($env:LOCALAPPDATA -and (Test-Path (Join-Path $env:LOCALAPPDATA "hermes"))) { Join-Path $env:LOCALAPPDATA "hermes" } else { Join-Path $HOME ".hermes" }
$env:HERMES_HOME = $HermesHome
$LogDir = Join-Path $HermesHome "logs\control-center"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$HermesVersionSource = "https://raw.githubusercontent.com/NousResearch/hermes-agent/main/pyproject.toml"
$ControlCenterVersionSource = "https://raw.githubusercontent.com/Neal86/Hermes-Control-Center/main/plugin.yaml"

function Read-VersionFile([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    try {
        $text = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
        if ($text -match '(?m)^version:\s*["'']?([^\s"'']+)["'']?\s*$') { return $Matches[1].Trim() }
    } catch {}
    return $null
}

function Get-RemoteVersion([string]$Uri, [string]$Pattern) {
    try {
        $text = (Invoke-WebRequest -UseBasicParsing -Uri $Uri -TimeoutSec 8).Content
        if ($text -match $Pattern) { return $Matches[1].Trim() }
    } catch {}
    return $null
}

function Get-HermesInstalledVersion {
    $cmd = Get-Command hermes -ErrorAction SilentlyContinue
    if (-not $cmd) { return $null }
    try {
        $text = (& $cmd.Source --version 2>$null | Out-String)
        if ($text -match '(?i)(?:^|[^0-9])v?([0-9]+\.[0-9]+\.[0-9]+)') { return $Matches[1] }
    } catch {}
    return $null
}

function Same-Version([string]$A, [string]$B) {
    if (-not $A -or -not $B) { return $false }
    try { return ([version](($A -split '[-+]',2)[0])) -eq ([version](($B -split '[-+]',2)[0])) } catch { return $A -eq $B }
}

function Show-Log([string]$Path) {
    if (Test-Path -LiteralPath $Path) {
        Get-Content -LiteralPath $Path -ErrorAction SilentlyContinue | ForEach-Object { Write-Host ([string]$_) }
    }
}

function Run-PowerShellFile {
    param([string]$Path, [string[]]$Arguments, [string]$LogName)
    if (-not (Test-Path -LiteralPath $Path)) {
        Write-Host "Missing script: $Path" -ForegroundColor Red
        return 2
    }
    $out = Join-Path $LogDir ($LogName + ".out.log")
    $err = Join-Path $LogDir ($LogName + ".err.log")
    Remove-Item $out,$err -Force -ErrorAction SilentlyContinue
    $args = @("-NoLogo","-NoProfile","-ExecutionPolicy","Bypass","-File",$Path) + $Arguments
    $proc = Start-Process -FilePath "powershell.exe" -ArgumentList $args -Wait -PassThru -NoNewWindow -RedirectStandardOutput $out -RedirectStandardError $err
    Show-Log $out
    Show-Log $err
    return [int]$proc.ExitCode
}

function Show-Menu {
    Clear-Host
    $hInstalled = Get-HermesInstalledVersion
    $hLatest = Get-RemoteVersion $HermesVersionSource '(?m)^version\s*=\s*["'']([^"'']+)["'']\s*$'
    $cInstalled = Read-VersionFile (Join-Path $HermesHome "plugins\hermes-extensions\plugin.yaml")
    $cLatest = Get-RemoteVersion $ControlCenterVersionSource '(?m)^version:\s*["'']?([^\s"'']+)["'']?\s*$'
    if (-not $cLatest) { $cLatest = Read-VersionFile (Join-Path $Root "plugin.yaml") }

    Write-Host "Hermes Control Center Setup" -ForegroundColor Green
    Write-Host "Hermes home: $HermesHome"
    Write-Host ("Hermes:         " + $(if ($hInstalled) { "v$hInstalled" } else { "not installed" }) + $(if ($hLatest) { "  latest v$hLatest" } else { "  latest unknown" }))
    Write-Host ("Control Center: " + $(if ($cInstalled) { "v$cInstalled" } else { "not installed" }) + $(if ($cLatest) { "  latest v$cLatest" } else { "  latest unknown" }))
    Write-Host ""
    Write-Host "  1. Install / update everything"
    Write-Host ("  2. Update Hermes only" + $(if (Same-Version $hInstalled $hLatest) { "  [already current]" } else { "" }))
    Write-Host ("  3. Install / update Control Center only" + $(if (Same-Version $cInstalled $cLatest) { "  [already current]" } else { "" }))
    Write-Host "  4. Repair Control Center"
    Write-Host "  5. Open Hermes Dashboard"
    Write-Host "  6. Exit"
    Write-Host ""
}

while ($true) {
    Show-Menu
    $choice = (Read-Host "Choose").Trim()
    if ($choice -in @("6","0")) { break }

    $code = 1
    switch ($choice) {
        "1" {
            Write-Host "`nRunning: Install / update everything" -ForegroundColor Cyan
            $code = Run-PowerShellFile $CoreSetup @("-Action","UpdateHermes","-NoPrompt","-NoDashboard") "hermes-update"
            if ($code -eq 0) { $code = Run-PowerShellFile $SafeInstaller @() "control-center-safe-install" }
        }
        "2" {
            Write-Host "`nRunning: Update Hermes" -ForegroundColor Cyan
            $code = Run-PowerShellFile $CoreSetup @("-Action","UpdateHermes","-NoPrompt","-NoDashboard") "hermes-update"
        }
        "3" {
            Write-Host "`nRunning: Update Control Center" -ForegroundColor Cyan
            $code = Run-PowerShellFile $SafeInstaller @() "control-center-safe-install"
        }
        "4" {
            Write-Host "`nRunning: Repair Control Center" -ForegroundColor Cyan
            $code = Run-PowerShellFile $SafeInstaller @("-Repair") "control-center-safe-repair"
        }
        "5" {
            Write-Host "`nRunning: Open Hermes Dashboard" -ForegroundColor Cyan
            $code = Run-PowerShellFile $Dashboard @() "dashboard-launch-wrapper"
        }
        default {
            Write-Host "`nInvalid selection. Please choose 1-6." -ForegroundColor Yellow
            [void](Read-Host "Press Enter to return to menu")
            continue
        }
    }

    Write-Host ""
    if ($code -eq 0) { Write-Host "Operation finished successfully." -ForegroundColor Green }
    else { Write-Host "Operation failed with exit code $code." -ForegroundColor Red; Write-Host "The Setup menu will remain open." -ForegroundColor Yellow }
    [void](Read-Host "Press Enter to return to menu")
}

Write-Host "`nSetup closed." -ForegroundColor Green
exit 0
