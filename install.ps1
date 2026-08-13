param(
    [switch]$NoEnable,
    [switch]$SkipDependencies
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Source = Split-Path -Parent $MyInvocation.MyCommand.Path
$HermesHome = if ($env:HERMES_HOME) { $env:HERMES_HOME } elseif (Test-Path (Join-Path $env:LOCALAPPDATA "hermes")) { Join-Path $env:LOCALAPPDATA "hermes" } else { Join-Path $HOME ".hermes" }
$PluginsRoot = Join-Path $HermesHome "plugins"
$Target = Join-Path $PluginsRoot "hermes-extensions"
$PlatformSource = Join-Path $Source "platforms\wechat-desktop"
$PlatformTarget = Join-Path $PluginsRoot "platforms\wechat-desktop"
$Requirements = Join-Path $Source "requirements-windows.txt"
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
        & $PythonExe -c "import sys; print(sys.executable)" 2>$null | Out-Null
        return $LASTEXITCODE -eq 0
    } catch { return $false }
}

function Find-HermesPython {
    $candidates = New-Object System.Collections.Generic.List[string]

    # Hermes official Windows installer v0.20+ uses hermes-agent\venv.
    foreach ($candidate in @(
        (Join-Path $HermesHome "hermes-agent\venv\Scripts\python.exe"),
        (Join-Path $HermesHome "hermes-agent\.venv\Scripts\python.exe"),
        (Join-Path $HermesHome "venv\Scripts\python.exe"),
        (Join-Path $HermesHome ".venv\Scripts\python.exe")
    )) { $candidates.Add($candidate) }

    foreach ($base in @($env:LOCALAPPDATA, $env:APPDATA)) {
        if (-not $base) { continue }
        foreach ($relative in @(
            "hermes\hermes-agent\venv\Scripts\python.exe",
            "hermes\hermes-agent\.venv\Scripts\python.exe",
            "hermes\venv\Scripts\python.exe",
            "hermes\.venv\Scripts\python.exe",
            "uv\tools\hermes-agent\Scripts\python.exe"
        )) { $candidates.Add((Join-Path $base $relative)) }
    }

    if ($HermesCommand) {
        try {
            $versionText = & $HermesCommand.Source --version 2>&1 | Out-String
            if ($versionText -match "(?m)^Project:\s*(.+?)\s*$") {
                $project = $Matches[1].Trim()
                foreach ($relative in @("venv\Scripts\python.exe", ".venv\Scripts\python.exe")) {
                    $candidates.Insert(0, (Join-Path $project $relative))
                }
                $site = [System.IO.DirectoryInfo]::new($project)
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
    "requirements-windows.txt",
    "platforms\wechat-desktop\plugin.yaml",
    "platforms\wechat-desktop\adapter.py"
)
foreach ($rel in $RequiredPaths) {
    $path = Join-Path $Source $rel
    if (-not (Test-Path -LiteralPath $path)) { throw "Hermes Control Center package is incomplete: missing $path" }
}

if (-not $HermesCommand) { throw "Hermes is not installed or is not on PATH." }
$Capabilities = [ordered]@{ plugins = $false; dashboard = $false; profile = $false; project = $false; cron = $false; kanban = $false }
foreach ($name in @("plugins", "dashboard", "profile", "project", "cron", "kanban")) {
    $Capabilities[$name] = Test-HermesCapability -HermesExe $HermesCommand.Source -Command $name
}
Write-Host "Hermes home: $HermesHome"
Write-Host "Detected Hermes capabilities:"
$Capabilities.GetEnumerator() | ForEach-Object { Write-Host ("  {0,-10} {1}" -f $_.Key, $_.Value) }
if (-not $Capabilities.profile) { throw "This Hermes build does not expose profile management; installation aborted." }
if (-not $Capabilities.plugins) { throw "This Hermes build does not expose plugin management; installation aborted." }

$HermesPython = Find-HermesPython
if (-not $HermesPython) {
    throw "Could not locate Hermes Python. Expected official venv under '$HermesHome\hermes-agent\venv' or a supported .venv/uv-tool layout."
}
Write-Host "Hermes Python: $HermesPython"

if (-not $SkipDependencies) {
    Write-Host "Installing Control Center dependencies into Hermes Python..."
    $installed = $false
    try {
        & $HermesPython -m pip --version 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) {
            & $HermesPython -m pip install -r $Requirements
            if ($LASTEXITCODE -eq 0) { $installed = $true }
        }
    } catch {}
    if (-not $installed) {
        $uv = Get-Command uv -ErrorAction SilentlyContinue
        if ($uv) {
            & $uv.Source pip install --python $HermesPython -r $Requirements
            if ($LASTEXITCODE -eq 0) { $installed = $true }
        }
    }
    if (-not $installed) { throw "Unable to install Control Center dependencies into Hermes Python." }
}

New-Item -ItemType Directory -Force -Path $PluginsRoot | Out-Null
$TxnRoot = Join-Path $PluginsRoot (".hermes-control-center-txn-" + [Guid]::NewGuid().ToString("N"))
$StagePlugin = Join-Path $TxnRoot "hermes-extensions"
$StagePlatform = Join-Path $TxnRoot "wechat-desktop"
$BackupPlugin = Join-Path $TxnRoot "backup-hermes-extensions"
$BackupPlatform = Join-Path $TxnRoot "backup-wechat-desktop"

try {
    Write-Host "Staging Hermes Control Center..."
    Copy-PluginTree -From $Source -To $StagePlugin
    New-Item -ItemType Directory -Force -Path $StagePlatform | Out-Null
    Get-ChildItem -LiteralPath $PlatformSource -Force | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $StagePlatform -Recurse -Force
    }

    & $HermesPython (Join-Path $StagePlugin "dashboard\build_bundle.py") --root (Join-Path $StagePlugin "dashboard")
    if ($LASTEXITCODE -ne 0) { throw "Dashboard bundle build failed with exit code $LASTEXITCODE." }

    foreach ($required in @(
        "plugin.yaml",
        "dashboard\manifest.json",
        "dashboard\dist\index.js",
        "dashboard\extended_api.py",
        "providers\service.py",
        "resources\context.py",
        "resources\bindings.py",
        "resources\policy.py",
        "resources\tools.py",
        "resources\wechat_bound.py",
        "wechat\runtime.py"
    )) {
        if (-not (Test-Path -LiteralPath (Join-Path $StagePlugin $required))) {
            throw "Staging validation failed: missing $required"
        }
    }

    if (Test-Path -LiteralPath $Target) { Move-Item -LiteralPath $Target -Destination $BackupPlugin -Force }
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

    & (Join-Path $Target "doctor.ps1") -Installed
    if ($LASTEXITCODE -ne 0) { throw "Installed doctor verification failed with exit code $LASTEXITCODE." }

    Write-Host "Hermes Control Center v0.5.1 install complete."
} catch {
    Write-Warning "Installation failed; restoring previous Control Center files."
    if (Test-Path -LiteralPath $Target) { Remove-Item -LiteralPath $Target -Recurse -Force -ErrorAction SilentlyContinue }
    if (Test-Path -LiteralPath $PlatformTarget) { Remove-Item -LiteralPath $PlatformTarget -Recurse -Force -ErrorAction SilentlyContinue }
    if (Test-Path -LiteralPath $BackupPlugin) { Move-Item -LiteralPath $BackupPlugin -Destination $Target -Force }
    if (Test-Path -LiteralPath $BackupPlatform) { Move-Item -LiteralPath $BackupPlatform -Destination $PlatformTarget -Force }
    throw
} finally {
    if (Test-Path -LiteralPath $TxnRoot) { Remove-Item -LiteralPath $TxnRoot -Recurse -Force -ErrorAction SilentlyContinue }
}
