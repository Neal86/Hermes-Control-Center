param()

$ErrorActionPreference = "Continue"
Set-StrictMode -Version Latest
$ProgressPreference = "SilentlyContinue"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$SetupScript = Join-Path $Root "Setup-Hermes-Control-Center.ps1"
$DashboardLauncher = Join-Path $Root "Dashboard-Launch.ps1"
$HermesHome = if ($env:HERMES_HOME) { $env:HERMES_HOME } elseif ($env:LOCALAPPDATA -and (Test-Path (Join-Path $env:LOCALAPPDATA "hermes"))) { Join-Path $env:LOCALAPPDATA "hermes" } else { Join-Path $HOME ".hermes" }
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

function Get-HermesInstalledVersion {
    $cmd = Get-Command hermes -ErrorAction SilentlyContinue
    if (-not $cmd) { return $null }
    try {
        $text = (& $cmd.Source --version 2>&1 | Out-String)
        if ($text -match '(?i)(?:^|[^0-9])v?([0-9]+\.[0-9]+\.[0-9]+)') { return $Matches[1] }
    } catch {}
    return $null
}

function Get-HermesLatestVersion {
    try {
        $text = (Invoke-WebRequest -UseBasicParsing -Uri $HermesVersionSource -TimeoutSec 8).Content
        if ($text -match '(?m)^version\s*=\s*["'']([^"'']+)["'']\s*$') { return $Matches[1].Trim() }
    } catch {}
    return $null
}

function Get-ControlCenterInstalledVersion {
    return Read-VersionFile (Join-Path $HermesHome "plugins\hermes-extensions\plugin.yaml")
}

function Get-ControlCenterLatestVersion {
    try {
        $text = (Invoke-WebRequest -UseBasicParsing -Uri $ControlCenterVersionSource -TimeoutSec 8).Content
        if ($text -match '(?m)^version:\s*["'']?([^\s"'']+)["'']?\s*$') { return $Matches[1].Trim() }
    } catch {}
    return Read-VersionFile (Join-Path $Root "plugin.yaml")
}

function Same-Version([string]$A, [string]$B) {
    if (-not $A -or -not $B) { return $false }
    try { return ([version](($A -split '[-+]', 2)[0])) -eq ([version](($B -split '[-+]', 2)[0])) } catch { return $A -eq $B }
}

function Show-Menu {
    Clear-Host
    $hInstalled = Get-HermesInstalledVersion
    $hLatest = Get-HermesLatestVersion
    $cInstalled = Get-ControlCenterInstalledVersion
    $cLatest = Get-ControlCenterLatestVersion

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

function Run-Script([string]$Script, [string[]]$Arguments = @()) {
    if (-not (Test-Path -LiteralPath $Script)) {
        Write-Host "Missing script: $Script" -ForegroundColor Red
        return 2
    }
    & powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File $Script @Arguments 2>&1 | Out-Host
    $code = $LASTEXITCODE
    if ($null -eq $code) { $code = 1 }
    return [int]$code
}

while ($true) {
    Show-Menu
    $choice = (Read-Host "Choose").Trim()
    if ($choice -in @("6", "0")) { break }

    $code = 1
    switch ($choice) {
        "1" {
            Write-Host ""
            Write-Host "Running: Install / update everything" -ForegroundColor Cyan
            $code = Run-Script $SetupScript @("-Action", "Install", "-NoDashboard")
        }
        "2" {
            Write-Host ""
            Write-Host "Running: Update Hermes" -ForegroundColor Cyan
            $code = Run-Script $SetupScript @("-Action", "UpdateHermes")
        }
        "3" {
            Write-Host ""
            Write-Host "Running: Update Control Center" -ForegroundColor Cyan
            $code = Run-Script $SetupScript @("-Action", "UpdatePlugin")
        }
        "4" {
            Write-Host ""
            Write-Host "Running: Repair Control Center" -ForegroundColor Cyan
            $code = Run-Script $SetupScript @("-Action", "Repair")
        }
        "5" {
            Write-Host ""
            Write-Host "Running: Open Hermes Dashboard" -ForegroundColor Cyan
            $code = Run-Script $DashboardLauncher
        }
        default {
            Write-Host ""
            Write-Host "Invalid selection. Please choose 1-6." -ForegroundColor Yellow
            [void](Read-Host "Press Enter to return to menu")
            continue
        }
    }

    Write-Host ""
    if ($code -eq 0) {
        Write-Host "Operation finished successfully." -ForegroundColor Green
    } else {
        Write-Host "Operation failed with exit code $code." -ForegroundColor Red
        Write-Host "The Setup menu will remain open." -ForegroundColor Yellow
    }
    [void](Read-Host "Press Enter to return to menu")
}

Write-Host ""
Write-Host "Setup closed." -ForegroundColor Green
exit 0
