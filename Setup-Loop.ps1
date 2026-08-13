param()

$ErrorActionPreference = "Continue"
Set-StrictMode -Version Latest
$ProgressPreference = "SilentlyContinue"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$SetupScript = Join-Path $Root "Setup-Hermes-Control-Center.ps1"
$HermesHome = if ($env:HERMES_HOME) { $env:HERMES_HOME } elseif ($env:LOCALAPPDATA -and (Test-Path (Join-Path $env:LOCALAPPDATA "hermes"))) { Join-Path $env:LOCALAPPDATA "hermes" } else { Join-Path $HOME ".hermes" }
$HermesVersionSource = "https://raw.githubusercontent.com/NousResearch/hermes-agent/main/pyproject.toml"
$ControlCenterVersionSource = "https://raw.githubusercontent.com/Neal86/Hermes-Control-Center/main/plugin.yaml"

function Read-TextFileVersion {
    param([string]$Path)
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
    return Read-TextFileVersion (Join-Path $HermesHome "plugins\hermes-extensions\plugin.yaml")
}

function Get-ControlCenterLatestVersion {
    try {
        $text = (Invoke-WebRequest -UseBasicParsing -Uri $ControlCenterVersionSource -TimeoutSec 8).Content
        if ($text -match '(?m)^version:\s*["'']?([^\s"'']+)["'']?\s*$') { return $Matches[1].Trim() }
    } catch {}
    return Read-TextFileVersion (Join-Path $Root "plugin.yaml")
}

function Same-Version {
    param([string]$A, [string]$B)
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

function Invoke-SetupAction {
    param([string]$Action)
    if (-not (Test-Path -LiteralPath $SetupScript)) {
        Write-Host "Missing Setup-Hermes-Control-Center.ps1" -ForegroundColor Red
        return 2
    }
    Write-Host ""
    Write-Host ("Running: " + $Action) -ForegroundColor Cyan
    Write-Host "------------------------------------------------------------"
    & powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File $SetupScript -Action $Action
    return $LASTEXITCODE
}

while ($true) {
    Show-Menu
    $choice = (Read-Host "Choose").Trim()
    $action = switch ($choice) {
        "1" { "Install" }
        "2" { "UpdateHermes" }
        "3" { "UpdatePlugin" }
        "4" { "Repair" }
        "5" { "Dashboard" }
        "6" { "Exit" }
        "0" { "Exit" }
        default { $null }
    }

    if ($action -eq "Exit") { break }
    if (-not $action) {
        Write-Host ""
        Write-Host "Invalid selection. Please choose 1-6." -ForegroundColor Yellow
        [void](Read-Host "Press Enter to return to menu")
        continue
    }

    $code = Invoke-SetupAction $action
    Write-Host ""
    if ($code -eq 0) {
        Write-Host "Operation finished." -ForegroundColor Green
    } else {
        Write-Host "Operation failed with exit code $code." -ForegroundColor Red
        Write-Host "The Setup menu will remain open." -ForegroundColor Yellow
    }
    [void](Read-Host "Press Enter to return to menu")
}

Write-Host ""
Write-Host "Setup closed." -ForegroundColor Green
exit 0
