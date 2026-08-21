param()

$ErrorActionPreference = "Continue"
Set-StrictMode -Version Latest
$ProgressPreference = "SilentlyContinue"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$CoreSetup = Join-Path $Root "Setup-Hermes-Control-Center.ps1"
$Dashboard = Join-Path $Root "Dashboard-Launch-v4.ps1"
$HermesHome = if ($env:HERMES_HOME) { $env:HERMES_HOME } elseif ($env:LOCALAPPDATA -and (Test-Path (Join-Path $env:LOCALAPPDATA "hermes"))) { Join-Path $env:LOCALAPPDATA "hermes" } else { Join-Path $HOME ".hermes" }
$env:HERMES_HOME = $HermesHome
$LogDir = Join-Path $HermesHome "logs\control-center"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$HermesVersionSource = "https://raw.githubusercontent.com/NousResearch/hermes-agent/main/pyproject.toml"
$ControlCenterVersionSource = "https://raw.githubusercontent.com/Neal86/Hermes-Control-Center/main/plugin.yaml"
$ControlCenterBranchApi = "https://api.github.com/repos/Neal86/Hermes-Control-Center/branches/main"

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
        $separator = if ($Uri.Contains("?")) { "&" } else { "?" }
        $freshUri = $Uri + $separator + "hcc_cb=" + [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
        $headers = @{ "Cache-Control" = "no-cache, no-store, max-age=0"; "Pragma" = "no-cache"; "User-Agent" = "Hermes-Control-Center-Setup" }
        $text = (Invoke-WebRequest -UseBasicParsing -Uri $freshUri -Headers $headers -TimeoutSec 8).Content
        if ($text -match $Pattern) { return $Matches[1].Trim() }
    } catch {}
    return $null
}

function Get-ControlCenterLatestVersion {
    try {
        $separator = if ($ControlCenterBranchApi.Contains("?")) { "&" } else { "?" }
        $freshUri = $ControlCenterBranchApi + $separator + "hcc_cb=" + [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
        $headers = @{ "Cache-Control" = "no-cache, no-store, max-age=0"; "Pragma" = "no-cache"; "User-Agent" = "Hermes-Control-Center-Setup" }
        $branch = (Invoke-WebRequest -UseBasicParsing -Uri $freshUri -Headers $headers -TimeoutSec 8).Content | ConvertFrom-Json
        $sha = [string]$branch.commit.sha
        if ($sha -match '^[0-9a-f]{40}$') {
            return Get-RemoteVersion ("https://raw.githubusercontent.com/Neal86/Hermes-Control-Center/" + $sha + "/plugin.yaml") '(?m)^version:\s*["'']?([^\s"'']+)["'']?\s*$'
        }
    } catch {}
    return Get-RemoteVersion $ControlCenterVersionSource '(?m)^version:\s*["'']?([^\s"'']+)["'']?\s*$'
}

function Get-HermesInstalledVersion {
    $official = Join-Path $HermesHome "hermes-agent\bin\hermes.exe"
    $cmd = if (Test-Path -LiteralPath $official) { $official } else { $found = Get-Command hermes -ErrorAction SilentlyContinue; if ($found) { $found.Source } else { $null } }
    if (-not $cmd) { return $null }
    try {
        $text = (& $cmd --version 2>$null | Out-String)
        if ($text -match '(?i)(?:^|[^0-9])v?([0-9]+\.[0-9]+\.[0-9]+)') { return $Matches[1] }
    } catch {}
    return $null
}

function Same-Version([string]$A, [string]$B) {
    if (-not $A -or -not $B) { return $false }
    try { return ([version](($A -split '[-+]',2)[0])) -eq ([version](($B -split '[-+]',2)[0])) } catch { return $A -eq $B }
}

function Run-Core([string]$Action, [string]$LogName) {
    if (-not (Test-Path -LiteralPath $CoreSetup -PathType Leaf)) {
        Write-Host "Missing script: $CoreSetup" -ForegroundColor Red
        return 2
    }
    $out = Join-Path $LogDir ($LogName + ".out.log")
    $err = Join-Path $LogDir ($LogName + ".err.log")
    Remove-Item $out,$err -Force -ErrorAction SilentlyContinue
    $args = @("-NoLogo","-NoProfile","-ExecutionPolicy","Bypass","-File",('"' + $CoreSetup + '"'),"-Action",$Action,"-NoPrompt","-NoDashboard")
    $proc = Start-Process -FilePath "powershell.exe" -ArgumentList $args -Wait -PassThru -NoNewWindow -RedirectStandardOutput $out -RedirectStandardError $err
    if (Test-Path $out) { Get-Content $out -ErrorAction SilentlyContinue | ForEach-Object { Write-Host $_ } }
    if (Test-Path $err) { Get-Content $err -ErrorAction SilentlyContinue | ForEach-Object { Write-Host $_ -ForegroundColor Yellow } }
    return [int]$proc.ExitCode
}

function Launch-DashboardDetached {
    if (-not (Test-Path -LiteralPath $Dashboard -PathType Leaf)) {
        Write-Host "Missing Dashboard launcher: $Dashboard" -ForegroundColor Red
        return 2
    }
    $out = Join-Path $LogDir "dashboard-menu-launch.out.log"
    $err = Join-Path $LogDir "dashboard-menu-launch.err.log"
    Remove-Item $out,$err -Force -ErrorAction SilentlyContinue
    try {
        $args = @("-NoLogo","-NoProfile","-ExecutionPolicy","Bypass","-File",('"' + $Dashboard + '"'))
        $proc = Start-Process -FilePath "powershell.exe" -ArgumentList $args -PassThru -WindowStyle Hidden -RedirectStandardOutput $out -RedirectStandardError $err
        Write-Host ("Dashboard launch started in background (PID " + $proc.Id + ").") -ForegroundColor Green
        Write-Host "The menu is available immediately; no Enter key is required." -ForegroundColor DarkGray
        return 0
    } catch {
        Write-Host ("Unable to start Dashboard launcher: " + $_.Exception.Message) -ForegroundColor Red
        return 2
    }
}

function Show-Menu {
    Clear-Host
    $hInstalled = Get-HermesInstalledVersion
    $hLatest = Get-RemoteVersion $HermesVersionSource '(?m)^version\s*=\s*["'']([^"'']+)["'']\s*$'
    $cInstalled = Read-VersionFile (Join-Path $HermesHome "plugins\hermes-extensions\plugin.yaml")
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

while ($true) {
    Show-Menu
    $choice = (Read-Host "Choose").Trim()
    if ($choice -in @("6","0")) { break }
    $code = 1
    switch ($choice) {
        "1" {
            Write-Host "`nRunning: Install / update everything" -ForegroundColor Cyan
            $code = Run-Core "UpdateHermes" "hermes-update"
            if ($code -eq 0) { $code = Run-Core "UpdatePlugin" "control-center-update" }
        }
        "2" { Write-Host "`nRunning: Update Hermes" -ForegroundColor Cyan; $code = Run-Core "UpdateHermes" "hermes-update" }
        "3" { Write-Host "`nRunning: Update Control Center" -ForegroundColor Cyan; $code = Run-Core "UpdatePlugin" "control-center-update" }
        "4" { Write-Host "`nRunning: Repair Control Center" -ForegroundColor Cyan; $code = Run-Core "Repair" "control-center-repair" }
        "5" {
            Write-Host "`nRunning: Open Hermes Dashboard" -ForegroundColor Cyan
            $code = Launch-DashboardDetached
            Start-Sleep -Milliseconds 350
            continue
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
