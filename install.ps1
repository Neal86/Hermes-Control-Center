param(
    [switch]$NoEnable,
    [switch]$SkipDependencies
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Source = Split-Path -Parent $MyInvocation.MyCommand.Path
$HermesHome = if ($env:HERMES_HOME) { $env:HERMES_HOME } else { Join-Path $HOME ".hermes" }
$PluginsRoot = Join-Path $HermesHome "plugins"
$Target = Join-Path $PluginsRoot "hermes-extensions"
$PlatformSource = Join-Path $Source "platforms\wechat-desktop"
$PlatformTarget = Join-Path $PluginsRoot "platforms\wechat-desktop"
$Requirements = Join-Path $Source "requirements-windows.txt"
$ConfigPath = Join-Path $HermesHome "config.yaml"
$HermesCommand = Get-Command hermes -ErrorAction SilentlyContinue

function Test-HermesCapability {
    param([string]$HermesExe, [string]$Command)
    try {
        $output = & $HermesExe $Command --help 2>&1 | Out-String
        if ($output -match "invalid choice|no such command|unknown command") { return $false }
        return $LASTEXITCODE -eq 0
    } catch { return $false }
}

function Test-PythonCandidate {
    param([string]$PythonExe)
    if (-not $PythonExe -or -not (Test-Path -LiteralPath $PythonExe)) { return $false }
    try {
        & $PythonExe -c "import sys; print(sys.executable)" | Out-Null
        return $LASTEXITCODE -eq 0
    } catch { return $false }
}

function Find-HermesPython {
    $candidates = New-Object System.Collections.Generic.List[string]
    foreach ($base in @($env:APPDATA, $env:LOCALAPPDATA)) {
        if ($base) {
            $candidates.Add((Join-Path $base "uv\tools\hermes-agent\Scripts\python.exe"))
            $candidates.Add((Join-Path $base "hermes\.venv\Scripts\python.exe"))
            $candidates.Add((Join-Path $base "hermes\hermes-agent\.venv\Scripts\python.exe"))
        }
    }
    $candidates.Add((Join-Path $HermesHome "hermes-agent\.venv\Scripts\python.exe"))
    $candidates.Add((Join-Path $HermesHome ".venv\Scripts\python.exe"))

    if ($HermesCommand) {
        try {
            $versionText = & $HermesCommand.Source --version 2>&1 | Out-String
            if ($versionText -match "(?m)^Project:\s*(.+?)\s*$") {
                $site = [System.IO.DirectoryInfo]::new($Matches[1].Trim())
                if ($site.Name -ieq "site-packages" -and $site.Parent -and $site.Parent.Parent) {
                    $candidates.Insert(0, (Join-Path $site.Parent.Parent.FullName "Scripts\python.exe"))
                }
            }
        } catch {}
    }

    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if ($uv) {
        try {
            $toolDir = (& $uv.Source tool dir 2>$null | Select-Object -First 1).Trim()
            if ($toolDir) { $candidates.Insert(0, (Join-Path $toolDir "hermes-agent\Scripts\python.exe")) }
        } catch {}
    }

    foreach ($candidate in $candidates | Select-Object -Unique) {
        if (Test-PythonCandidate $candidate) { return $candidate }
    }
    return $null
}

function Copy-PluginTree {
    param([string]$From, [string]$To)
    New-Item -ItemType Directory -Force -Path $To | Out-Null
    Get-ChildItem -LiteralPath $From -Force | Where-Object {
        $_.Name -notin @(
            ".git", ".github", "__pycache__", ".pytest_cache", "platforms", "tests", "release",
            "Setup.cmd", "Setup-Hermes-Control-Center.ps1"
        )
    } | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $To -Recurse -Force
    }
}

function Restore-Backup {
    param([string]$Backup, [string]$Destination)
    if (Test-Path -LiteralPath $Destination) { Remove-Item -LiteralPath $Destination -Recurse -Force }
    if ($Backup -and (Test-Path -LiteralPath $Backup)) { Move-Item -LiteralPath $Backup -Destination $Destination -Force }
}

$RequiredPaths = @(
    "plugin.yaml",
    "dashboard\manifest.json",
    "dashboard\plugin_api.py",
    "dashboard\extended_api.py",
    "dashboard\build_bundle.py",
    "dashboard\src\api.js",
    "dashboard\src\components.js",
    "dashboard\src\app.js",
    "dashboard\src\index.js",
    "doctor.ps1",
    "compatibility.py",
    "management\overview.py",
    "management\service.py",
    "task_center\service_v3.py",
    "providers\__init__.py",
    "providers\service.py",
    "resources\__init__.py",
    "resources\context.py",
    "resources\discovery.py",
    "resources\registry.py",
    "resources\bindings.py",
    "resources\policy.py",
    "resources\tools.py",
    "resources\wechat_bound.py",
    "wechat\adapter.py",
    "wechat\runtime.py",
    "requirements-windows.txt"
)
foreach ($rel in $RequiredPaths) {
    $path = Join-Path $Source $rel
    if (-not (Test-Path -LiteralPath $path)) { throw "Hermes Control Center package is incomplete: missing $path" }
}
if (-not (Test-Path -LiteralPath (Join-Path $PlatformSource "plugin.yaml"))) { throw "Hermes Control Center package is incomplete: missing WeChat platform manifest" }

$Capabilities = [ordered]@{ hermes = [bool]$HermesCommand; plugins = $false; dashboard = $false; profile = $false; project = $false; cron = $false; kanban = $false }
if ($HermesCommand) {
    foreach ($name in @("plugins", "dashboard", "profile", "project", "cron", "kanban")) {
        $Capabilities[$name] = Test-HermesCapability -HermesExe $HermesCommand.Source -Command $name
    }
}
Write-Host "Hermes home: $HermesHome"
Write-Host "Detected Hermes capabilities:"
$Capabilities.GetEnumerator() | ForEach-Object { Write-Host ("  {0,-10} {1}" -f $_.Key, $_.Value) }
if (-not $Capabilities.project) { Write-Warning "Native 'hermes project' is unavailable. Projects will be disabled; Agents, Tasks, Providers, Resources and WeChat remain available." }
if (-not $Capabilities.profile) { throw "This Hermes build does not expose profile management; installation aborted." }
if (-not $Capabilities.plugins) { throw "This Hermes build does not expose plugin management; installation aborted." }

$HermesPython = Find-HermesPython
if (-not $HermesPython) { throw "Could not locate the Python interpreter used by Hermes. Refusing to install dependencies into an unrelated system Python." }
Write-Host "Hermes Python: $HermesPython"

if (-not $SkipDependencies) {
    Write-Host "Installing plugin dependencies into the Hermes Python environment..."
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    $installed = $false
    try {
        & $HermesPython -m pip --version 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) {
            & $HermesPython -m pip install -r $Requirements
            if ($LASTEXITCODE -ne 0) { throw "pip exited with code $LASTEXITCODE" }
            $installed = $true
        }
    } catch {}
    if (-not $installed -and $uv) {
        & $uv.Source pip install --python $HermesPython -r $Requirements
        if ($LASTEXITCODE -ne 0) { throw "uv pip install exited with code $LASTEXITCODE" }
        $installed = $true
    }
    if (-not $installed) { throw "Unable to install dependencies into Hermes Python." }
}

& $HermesPython -c "import yaml, croniter; print('shared dependencies ok')"
if ($LASTEXITCODE -ne 0) { throw "Shared dependency import validation failed." }
& $HermesPython -c "import pywinauto, pyperclip; print('Windows WeChat dependencies ok')"
if ($LASTEXITCODE -ne 0) { throw "Windows WeChat dependency import validation failed." }

New-Item -ItemType Directory -Force -Path $PluginsRoot | Out-Null
$TxnRoot = Join-Path $PluginsRoot (".hermes-control-center-txn-" + [Guid]::NewGuid().ToString("N"))
$StagePlugin = Join-Path $TxnRoot "stage\hermes-extensions"
$StagePlatform = Join-Path $TxnRoot "stage\wechat-desktop"
$BackupPlugin = Join-Path $TxnRoot "backup\hermes-extensions"
$BackupPlatform = Join-Path $TxnRoot "backup\wechat-desktop"
$BackupConfig = Join-Path $TxnRoot "backup\config.yaml"
$ConfigExisted = Test-Path -LiteralPath $ConfigPath
New-Item -ItemType Directory -Force -Path (Split-Path $StagePlugin -Parent) | Out-Null
New-Item -ItemType Directory -Force -Path (Split-Path $BackupPlugin -Parent) | Out-Null
if ($ConfigExisted) { Copy-Item -LiteralPath $ConfigPath -Destination $BackupConfig -Force }

try {
    Write-Host "Staging Hermes Control Center..."
    Copy-PluginTree -From $Source -To $StagePlugin
    & $HermesPython (Join-Path $StagePlugin "dashboard\build_bundle.py") --root (Join-Path $StagePlugin "dashboard")
    if ($LASTEXITCODE -ne 0) { throw "Dashboard bundle build failed with exit code $LASTEXITCODE." }

    New-Item -ItemType Directory -Force -Path $StagePlatform | Out-Null
    Get-ChildItem -LiteralPath $PlatformSource -Force | ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination $StagePlatform -Recurse -Force }

    foreach ($required in @(
        (Join-Path $StagePlugin "plugin.yaml"),
        (Join-Path $StagePlugin "dashboard\manifest.json"),
        (Join-Path $StagePlugin "dashboard\dist\index.js"),
        (Join-Path $StagePlugin "dashboard\extended_api.py"),
        (Join-Path $StagePlugin "management\overview.py"),
        (Join-Path $StagePlugin "task_center\service_v3.py"),
        (Join-Path $StagePlugin "providers\service.py"),
        (Join-Path $StagePlugin "resources\context.py"),
        (Join-Path $StagePlugin "resources\bindings.py"),
        (Join-Path $StagePlugin "resources\policy.py"),
        (Join-Path $StagePlugin "resources\tools.py"),
        (Join-Path $StagePlugin "resources\wechat_bound.py"),
        (Join-Path $StagePlugin "wechat\runtime.py"),
        (Join-Path $StagePlatform "plugin.yaml")
    )) {
        if (-not (Test-Path -LiteralPath $required)) { throw "Staging validation failed: missing $required" }
    }

    & $HermesPython -m compileall -q $StagePlugin
    if ($LASTEXITCODE -ne 0) { throw "Python compile validation failed in staging." }

    if (Test-Path -LiteralPath $Target) { Write-Host "Backing up current Hermes Control Center..."; Move-Item -LiteralPath $Target -Destination $BackupPlugin -Force }
    if (Test-Path -LiteralPath $PlatformTarget) { Move-Item -LiteralPath $PlatformTarget -Destination $BackupPlatform -Force }

    New-Item -ItemType Directory -Force -Path (Split-Path $PlatformTarget -Parent) | Out-Null
    Move-Item -LiteralPath $StagePlugin -Destination $Target -Force
    Move-Item -LiteralPath $StagePlatform -Destination $PlatformTarget -Force

    if (-not $NoEnable) {
        foreach ($PluginName in @("hermes-extensions", "wechat-desktop")) {
            & $HermesCommand.Source plugins enable $PluginName
            if ($LASTEXITCODE -ne 0) { throw "Hermes could not enable plugin '$PluginName'." }
        }
    }

    $installedList = & $HermesCommand.Source plugins list --plain --no-bundled 2>&1 | Out-String
    if ($installedList -notmatch "hermes-extensions") { throw "Hermes did not discover hermes-extensions after installation." }
    if ($installedList -notmatch "wechat-desktop") { throw "Hermes did not discover wechat-desktop after installation." }

    $DashboardRescanned = $false
    if ($Capabilities.dashboard) {
        try {
            $status = & $HermesCommand.Source dashboard --status 2>&1 | Out-String
            if ($status -notmatch "No hermes dashboard processes running") {
                Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:9119/api/dashboard/plugins/rescan" -TimeoutSec 5 | Out-Null
                $DashboardRescanned = $true
                Write-Host "Dashboard plugin rescan completed."
            }
        } catch { Write-Warning "Dashboard hot rescan was unavailable: $($_.Exception.Message)" }
    }

    & (Join-Path $Target "doctor.ps1") -Installed
    if ($LASTEXITCODE -ne 0) { throw "Installed doctor verification failed with exit code $LASTEXITCODE." }

    Write-Host "Hermes Control Center v0.5.1 install complete."
    Write-Host "Dashboard hot rescan: $DashboardRescanned"
    if (-not $Capabilities.project) { Write-Host "Projects: disabled for this Hermes build; the rest of Control Center remains available." }
    Write-Host "If Dashboard backend code changed, restart only 'hermes dashboard'."
    Write-Host "For WeChat platform Python changes, restart the relevant Hermes gateway."
} catch {
    Write-Error "Installation failed; rolling back previous plugin files and Hermes plugin configuration. $($_.Exception.Message)"
    try { Restore-Backup -Backup $BackupPlugin -Destination $Target } catch { Write-Warning "Plugin rollback failed: $($_.Exception.Message)" }
    try { Restore-Backup -Backup $BackupPlatform -Destination $PlatformTarget } catch { Write-Warning "Platform rollback failed: $($_.Exception.Message)" }
    try {
        if ($ConfigExisted -and (Test-Path -LiteralPath $BackupConfig)) { Copy-Item -LiteralPath $BackupConfig -Destination $ConfigPath -Force }
        elseif (-not $ConfigExisted -and (Test-Path -LiteralPath $ConfigPath)) { Remove-Item -LiteralPath $ConfigPath -Force }
    } catch { Write-Warning "Hermes config rollback failed: $($_.Exception.Message)" }
    throw
} finally {
    if (Test-Path -LiteralPath $TxnRoot) { Remove-Item -LiteralPath $TxnRoot -Recurse -Force -ErrorAction SilentlyContinue }
}
