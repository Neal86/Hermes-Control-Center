param()

$ErrorActionPreference = "Continue"
Set-StrictMode -Version Latest
$ProgressPreference = "SilentlyContinue"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$CoreSetup = Join-Path $Root "Setup-Hermes-Control-Center.ps1"
$SafeInstaller = Join-Path $Root "Install-Control-Center-Safe.ps1"
$Dashboard = Join-Path $Root "Dashboard-Launch-v3.ps1"
$PluginStateHelper = Join-Path $Root "scripts\plugin_state.py"
$HermesHome = if ($env:HERMES_HOME) { $env:HERMES_HOME } elseif ($env:LOCALAPPDATA -and (Test-Path (Join-Path $env:LOCALAPPDATA "hermes"))) { Join-Path $env:LOCALAPPDATA "hermes" } else { Join-Path $HOME ".hermes" }
$env:HERMES_HOME = $HermesHome
$ConfigPath = Join-Path $HermesHome "config.yaml"
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
    if (Test-Path -LiteralPath $Path) { Get-Content -LiteralPath $Path -ErrorAction SilentlyContinue | ForEach-Object { Write-Host ([string]$_) } }
}
function Quote-ProcessArgument([string]$Value) {
    if ($null -eq $Value) { return '""' }
    return '"' + ($Value -replace '(\\*)"', '$1$1\"' -replace '(\\+)$', '$1$1') + '"'
}
function Run-PowerShellFile {
    param([string]$Path,[string[]]$Arguments,[string]$LogName)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { Write-Host "Missing script: $Path" -ForegroundColor Red; return 2 }
    if ([System.IO.Path]::GetExtension($Path) -ine ".ps1") { Write-Host "Invalid PowerShell script path: $Path" -ForegroundColor Red; return 2 }
    $out = Join-Path $LogDir ($LogName + ".out.log")
    $err = Join-Path $LogDir ($LogName + ".err.log")
    Remove-Item $out,$err -Force -ErrorAction SilentlyContinue
    $processArgs = @("-NoLogo","-NoProfile","-ExecutionPolicy","Bypass","-File",(Quote-ProcessArgument $Path))
    foreach ($argument in $Arguments) { $processArgs += (Quote-ProcessArgument ([string]$argument)) }
    $proc = Start-Process -FilePath "powershell.exe" -ArgumentList $processArgs -Wait -PassThru -NoNewWindow -RedirectStandardOutput $out -RedirectStandardError $err
    Show-Log $out; Show-Log $err
    return [int]$proc.ExitCode
}
function Find-HermesPython {
    foreach ($path in @(
        (Join-Path $HermesHome "hermes-agent\venv\Scripts\python.exe"),
        (Join-Path $HermesHome "hermes-agent\.venv\Scripts\python.exe"),
        (Join-Path $HermesHome "venv\Scripts\python.exe"),
        (Join-Path $HermesHome ".venv\Scripts\python.exe")
    )) { if (Test-Path -LiteralPath $path) { return $path } }
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if ($uv) {
        try {
            $toolDir = (& $uv.Source tool dir 2>$null | Select-Object -First 1).Trim()
            if ($toolDir) {
                $candidate = Join-Path $toolDir "hermes-agent\Scripts\python.exe"
                if (Test-Path -LiteralPath $candidate) { return $candidate }
            }
        } catch {}
    }
    return $null
}
function Test-PackageComplete {
    $required = @(
        "plugin.yaml","__init__.py","compatibility.py","doctor.ps1","Install-Control-Center-Safe.ps1","install.ps1",
        "dashboard\manifest.json","dashboard\plugin_api.py","dashboard\plugin_api_core.py","dashboard\extra_api.py","dashboard\api_smoke.py","dashboard\build_bundle.py",
        "dashboard\src\api.js","dashboard\src\components.js","dashboard\src\app.js","dashboard\src\control_center_v2.js","dashboard\src\index.js",
        "management\service.py","management\routed_service.py","task_center\service_v3.py","providers\service.py",
        "resources\context.py","resources\bindings.py","resources\policy.py","resources\tools.py","resources\wechat_bound.py","wechat\runtime.py",
        "platforms\wechat-desktop\plugin.yaml","platforms\wechat-desktop\adapter.py","platforms\wechat-desktop\adapter_legacy.py","scripts\plugin_state.py"
    )
    $missing = @()
    foreach ($rel in $required) { if (-not (Test-Path -LiteralPath (Join-Path $Root $rel))) { $missing += $rel } }
    if ($missing.Count) {
        Write-Host "Control Center package is incomplete:" -ForegroundColor Red
        $missing | ForEach-Object { Write-Host ("  missing: " + $_) -ForegroundColor Red }
        return $false
    }
    return $true
}
function Normalize-PluginState {
    param([ValidateSet("prepare","finalize")][string]$Mode = "finalize")
    $python = Find-HermesPython
    if (-not $python -or -not (Test-Path -LiteralPath $PluginStateHelper)) { return 2 }
    $out = Join-Path $LogDir ("plugin-state-" + $Mode + ".out.log")
    $err = Join-Path $LogDir ("plugin-state-" + $Mode + ".err.log")
    Remove-Item $out,$err -Force -ErrorAction SilentlyContinue
    $proc = Start-Process -FilePath $python -ArgumentList @($PluginStateHelper,$ConfigPath,$Mode) -WorkingDirectory $Root -Wait -PassThru -NoNewWindow -RedirectStandardOutput $out -RedirectStandardError $err
    Show-Log $out; Show-Log $err
    return [int]$proc.ExitCode
}
function Stop-DashboardAfterPluginUpdate {
    $hermes = Get-Command hermes -ErrorAction SilentlyContinue
    if (-not $hermes) { return 0 }
    $out = Join-Path $LogDir "dashboard-stop.out.log"
    $err = Join-Path $LogDir "dashboard-stop.err.log"
    Remove-Item $out,$err -Force -ErrorAction SilentlyContinue
    try {
        $proc = Start-Process -FilePath $hermes.Source -ArgumentList @("dashboard","--stop") -Wait -PassThru -NoNewWindow -RedirectStandardOutput $out -RedirectStandardError $err
        Show-Log $out; Show-Log $err
        if ($proc.ExitCode -ne 0) { Write-Host "Dashboard stop returned exit code $($proc.ExitCode); continuing." -ForegroundColor Yellow }
    } catch { Write-Host "Dashboard stop failed: $($_.Exception.Message)" -ForegroundColor Yellow }
    return 0
}
function Restore-Config([string]$Backup,[bool]$OriginallyExisted) {
    if ($OriginallyExisted -and (Test-Path -LiteralPath $Backup)) {
        Copy-Item -LiteralPath $Backup -Destination $ConfigPath -Force
    } elseif (-not $OriginallyExisted -and (Test-Path -LiteralPath $ConfigPath)) {
        Remove-Item -LiteralPath $ConfigPath -Force -ErrorAction SilentlyContinue
    }
}
function Install-ControlCenter([switch]$Repair) {
    if (-not (Test-PackageComplete)) { return 3 }
    $backup = Join-Path $env:TEMP ("hermes-control-center-config-" + [Guid]::NewGuid().ToString("N") + ".yaml")
    $configExisted = Test-Path -LiteralPath $ConfigPath
    if ($configExisted) { Copy-Item -LiteralPath $ConfigPath -Destination $backup -Force }
    try {
        $code = Normalize-PluginState -Mode "prepare"
        if ($code -ne 0) { Restore-Config $backup $configExisted; return $code }
        $installerArgs = if ($Repair) { @("-Repair") } else { @() }
        $code = Run-PowerShellFile $SafeInstaller $installerArgs $(if ($Repair) { "control-center-safe-repair" } else { "control-center-safe-install" })
        if ($code -ne 0) { Restore-Config $backup $configExisted; return $code }
        $code = Normalize-PluginState -Mode "finalize"
        if ($code -ne 0) { Restore-Config $backup $configExisted; return $code }
        [void](Stop-DashboardAfterPluginUpdate)
        return 0
    } finally {
        Remove-Item -LiteralPath $backup -Force -ErrorAction SilentlyContinue
    }
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
            if ($code -eq 0) { $code = Install-ControlCenter }
        }
        "2" { Write-Host "`nRunning: Update Hermes" -ForegroundColor Cyan; $code = Run-PowerShellFile $CoreSetup @("-Action","UpdateHermes","-NoPrompt","-NoDashboard") "hermes-update" }
        "3" { Write-Host "`nRunning: Update Control Center" -ForegroundColor Cyan; $code = Install-ControlCenter }
        "4" { Write-Host "`nRunning: Repair Control Center" -ForegroundColor Cyan; $code = Install-ControlCenter -Repair }
        "5" { Write-Host "`nRunning: Open Hermes Dashboard" -ForegroundColor Cyan; $code = Run-PowerShellFile $Dashboard @() "dashboard-launch-wrapper" }
        default { Write-Host "`nInvalid selection. Please choose 1-6." -ForegroundColor Yellow; [void](Read-Host "Press Enter to return to menu"); continue }
    }
    Write-Host ""
    if ($code -eq 0) { Write-Host "Operation finished successfully." -ForegroundColor Green }
    else { Write-Host "Operation failed with exit code $code." -ForegroundColor Red; Write-Host "The Setup menu will remain open." -ForegroundColor Yellow }
    [void](Read-Host "Press Enter to return to menu")
}
Write-Host "`nSetup closed." -ForegroundColor Green
exit 0
