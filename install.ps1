param(
    [switch]$NoEnable,
    [switch]$SkipDependencies
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$ProgressPreference = "SilentlyContinue"

$Source = Split-Path -Parent $MyInvocation.MyCommand.Path
$HermesHome = if ($env:HERMES_HOME) { $env:HERMES_HOME } elseif ($env:LOCALAPPDATA -and (Test-Path (Join-Path $env:LOCALAPPDATA "hermes"))) { Join-Path $env:LOCALAPPDATA "hermes" } else { Join-Path $HOME ".hermes" }
$env:HERMES_HOME = $HermesHome
$PluginsRoot = Join-Path $HermesHome "plugins"
$ConfigPath = Join-Path $HermesHome "config.yaml"
$Target = Join-Path $PluginsRoot "hermes-extensions"
$PlatformSource = Join-Path $Source "platforms\wechat-desktop"
$PlatformTarget = Join-Path $PluginsRoot "wechat-desktop"
$LegacyNestedPlatformTarget = Join-Path $PluginsRoot "platforms\wechat-desktop"
$Requirements = Join-Path $Source "requirements-windows.txt"
$HermesCommand = Get-Command hermes -ErrorAction SilentlyContinue

function Get-GatewayPidPath {
    param([string]$Profile)
    if (-not $Profile -or $Profile -eq "default") { return Join-Path $HermesHome "gateway.pid" }
    return Join-Path (Join-Path (Join-Path $HermesHome "profiles") $Profile) "gateway.pid"
}

function Read-GatewayPid {
    param([string]$PidPath)
    if (-not $PidPath -or -not (Test-Path -LiteralPath $PidPath)) { return 0 }
    try {
        $raw = (Get-Content -LiteralPath $PidPath -Raw -ErrorAction Stop).Trim()
        if (-not $raw) { return 0 }
        if ($raw.StartsWith("{")) {
            try {
                $payload = $raw | ConvertFrom-Json -ErrorAction Stop
                $jsonPid = 0
                if ($null -ne $payload.pid -and [int]::TryParse(([string]$payload.pid), [ref]$jsonPid) -and $jsonPid -gt 0) { return $jsonPid }
            } catch {}
            return 0
        }
        $legacyPid = 0
        if ([int]::TryParse($raw, [ref]$legacyPid) -and $legacyPid -gt 0) { return $legacyPid }
    } catch {}
    return 0
}

function Get-RunningGatewayProfiles {
    $running = New-Object System.Collections.Generic.List[string]
    $candidates = @(@{ Name = "default"; Pid = (Get-GatewayPidPath -Profile "default") })
    $profilesRoot = Join-Path $HermesHome "profiles"
    if (Test-Path -LiteralPath $profilesRoot) {
        Get-ChildItem -LiteralPath $profilesRoot -Directory -ErrorAction SilentlyContinue | ForEach-Object {
            $candidates += @{ Name = $_.Name; Pid = (Get-GatewayPidPath -Profile $_.Name) }
        }
    }
    foreach ($candidate in $candidates) {
        $pidValue = Read-GatewayPid -PidPath $candidate.Pid
        if ($pidValue -gt 0 -and (Get-Process -Id $pidValue -ErrorAction SilentlyContinue)) {
            if (-not $running.Contains([string]$candidate.Name)) { $running.Add([string]$candidate.Name) }
        }
    }
    return @($running)
}

function Get-RunningDashboardPort {
    try {
        $home = $HermesHome.ToLowerInvariant()
        foreach ($proc in Get-CimInstance Win32_Process -ErrorAction Stop) {
            $cmd = [string]$proc.CommandLine
            $combined = (([string]$proc.ExecutablePath) + " " + $cmd).ToLowerInvariant()
            if (-not $combined.Contains($home) -or -not $combined.Contains("dashboard") -or -not $combined.Contains("hermes")) { continue }
            if ($cmd -match '(?i)--port\s+(\d+)') { return [int]$Matches[1] }
            return 9119
        }
    } catch {}
    return 0
}

function Refresh-IsolatedProfileRuntime {
    param([string]$PythonExe, [string]$TempRoot)
    $helper = Join-Path $TempRoot "refresh-isolated-runtime.py"
    @'
from __future__ import annotations
import importlib.util, sys
from pathlib import Path
root = Path(sys.argv[1]).expanduser().resolve()
path = root / "plugins" / "hermes-extensions" / "hcc_gateway" / "lifecycle.py"
spec = importlib.util.spec_from_file_location("hcc_installer_gateway_lifecycle", path)
if spec is None or spec.loader is None:
    raise SystemExit(f"Unable to load {path}")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module._persist_independent_gateway_config(root)
profiles = root / "profiles"
if profiles.is_dir():
    for profile in sorted((item for item in profiles.iterdir() if item.is_dir()), key=lambda item: item.name.lower()):
        module._sync_enabled_user_plugins(root, profile)
print("Independent Gateway runtime state refreshed.")
'@ | Set-Content -LiteralPath $helper -Encoding UTF8
    $output = & $PythonExe $helper $HermesHome 2>&1
    $exitCode = $LASTEXITCODE
    $output | ForEach-Object { Write-Host ([string]$_) }
    if ($exitCode -ne 0) { throw "Independent Gateway runtime refresh failed (exit code $exitCode)." }
}

function Restart-PreviouslyRunningRuntime {
    param([string[]]$GatewayProfiles, [int]$DashboardPort)
    if (-not $HermesCommand) { return }
    foreach ($profile in $GatewayProfiles) {
        $pidPath = Get-GatewayPidPath -Profile $profile
        $beforePid = Read-GatewayPid -PidPath $pidPath
        Write-Stage ("Reloading Gateway runtime for profile " + $profile + " (pid " + $beforePid + ")")
        if ($profile -eq "default") { & $HermesCommand.Source gateway restart | Out-Host }
        else { & $HermesCommand.Source -p $profile gateway restart | Out-Host }
        if ($LASTEXITCODE -ne 0) { throw "Gateway restart failed for profile '$profile'." }
        $afterPid = 0
        $reloaded = $false
        for ($attempt = 0; $attempt -lt 20; $attempt++) {
            Start-Sleep -Milliseconds 250
            $afterPid = Read-GatewayPid -PidPath $pidPath
            if ($afterPid -gt 0 -and $afterPid -ne $beforePid -and (Get-Process -Id $afterPid -ErrorAction SilentlyContinue)) {
                $reloaded = $true
                break
            }
        }
        if (-not $reloaded) { throw "Gateway restart verification failed for profile '$profile' (before=$beforePid after=$afterPid)." }
        Write-Stage ("Gateway runtime reloaded for profile " + $profile + " (pid " + $afterPid + ")")
    }
    if ($DashboardPort -gt 0) {
        Write-Stage ("Reloading Dashboard runtime on port " + $DashboardPort)
        try { & $HermesCommand.Source dashboard --stop 2>&1 | Out-Host } catch {}
        Start-Sleep -Milliseconds 700
        Start-Process -FilePath $HermesCommand.Source -ArgumentList @("dashboard","--skip-build","--no-open","--host","127.0.0.1","--port",[string]$DashboardPort) -WindowStyle Hidden | Out-Null
    }
}

function Write-Stage { param([string]$Message) Write-Host ("  -> " + $Message) -ForegroundColor Cyan }
function Read-PluginVersion {
    param([string]$ManifestPath)
    try {
        $text = Get-Content -LiteralPath $ManifestPath -Raw -Encoding UTF8
        if ($text -match '(?m)^version:\s*["'']?([^\s"'']+)["'']?\s*$') { return $Matches[1].Trim() }
    } catch {}
    return "unknown"
}
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
    try { & $PythonExe -c "import sys; print(sys.executable)" 2>$null | Out-Null; return $LASTEXITCODE -eq 0 } catch { return $false }
}
function Find-HermesPython {
    $candidates = New-Object System.Collections.Generic.List[string]
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
                foreach ($relative in @("venv\Scripts\python.exe", ".venv\Scripts\python.exe")) { $candidates.Insert(0, (Join-Path $project $relative)) }
                $site = [System.IO.DirectoryInfo]::new($project)
                if ($site.Name -ieq "site-packages" -and $site.Parent -and $site.Parent.Parent) { $candidates.Insert(0, (Join-Path $site.Parent.Parent.FullName "Scripts\python.exe")) }
            }
        } catch {}
    }
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if ($uv) {
        try { $toolDir = (& $uv.Source tool dir 2>$null | Select-Object -First 1).Trim(); if ($toolDir) { $candidates.Insert(0, (Join-Path $toolDir "hermes-agent\Scripts\python.exe")) } } catch {}
    }
    foreach ($candidate in $candidates | Select-Object -Unique) { if (Test-PythonCandidate $candidate) { return $candidate } }
    return $null
}
function Copy-RuntimeTree {
    param([string]$From, [string]$To)
    New-Item -ItemType Directory -Force -Path $To | Out-Null
    $files = @("plugin.yaml", "__init__.py", "schemas.py", "tools.py", "compatibility.py", "gateway_isolation.py", "business_guard.py", "doctor.ps1", "requirements.txt", "requirements-windows.txt")
    $dirs = @("dashboard", "management", "task_center", "providers", "resources", "wechat", "browser", "hcc_gateway")
    foreach ($rel in $files) {
        $src = Join-Path $From $rel
        if (Test-Path -LiteralPath $src) { Write-Stage "Copying $rel"; Copy-Item -LiteralPath $src -Destination (Join-Path $To $rel) -Force }
    }
    foreach ($rel in $dirs) {
        $src = Join-Path $From $rel
        if (Test-Path -LiteralPath $src) { Write-Stage "Copying $rel\"; Copy-Item -LiteralPath $src -Destination (Join-Path $To $rel) -Recurse -Force }
    }
}
function Enable-ControlCenterPlugins {
    param([string]$PythonExe, [string]$TempRoot, [string]$ConfigFile)
    $helper = Join-Path $TempRoot "enable-plugins.py"
    @'
from __future__ import annotations
import os, sys, tempfile
from pathlib import Path
import yaml
path = Path(sys.argv[1]).expanduser().resolve()
try:
    value = yaml.safe_load(path.read_text("utf-8")) if path.exists() else {}
except Exception as exc:
    raise SystemExit(f"Unable to read Hermes config {path}: {exc}")
cfg = value if isinstance(value, dict) else {}
plugins = cfg.get("plugins")
if not isinstance(plugins, dict):
    plugins = {}; cfg["plugins"] = plugins
raw = plugins.get("enabled")
enabled = raw if isinstance(raw, list) else []
clean = []
for item in enabled:
    name = str(item or "").strip().replace("\\", "/")
    lower = name.lower()
    if not name or ".hermes-control-center-txn-" in lower or "backup-hermes-extensions" in lower or "backup-wechat-desktop" in lower:
        continue
    if name not in clean: clean.append(name)
for name in ("hermes-extensions", "wechat-desktop"):
    if name not in clean: clean.append(name)
plugins["enabled"] = clean
path.parent.mkdir(parents=True, exist_ok=True)
fd, tmp_name = tempfile.mkstemp(prefix="config.", suffix=".yaml.tmp", dir=str(path.parent))
try:
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
        yaml.safe_dump(cfg, handle, sort_keys=False, allow_unicode=True)
    os.replace(tmp_name, path)
finally:
    try: os.unlink(tmp_name)
    except OSError: pass
verify = yaml.safe_load(path.read_text("utf-8")) or {}
actual = ((verify.get("plugins") or {}).get("enabled") or []) if isinstance(verify, dict) else []
missing = [name for name in ("hermes-extensions", "wechat-desktop") if name not in actual]
if missing: raise SystemExit("plugins.enabled verification failed; missing: " + ", ".join(missing))
print("Enabled plugins: " + ", ".join(str(x) for x in actual))
'@ | Set-Content -LiteralPath $helper -Encoding UTF8
    $output = & $PythonExe $helper $ConfigFile 2>&1
    $exitCode = $LASTEXITCODE
    $output | ForEach-Object { Write-Host ([string]$_) }
    if ($exitCode -ne 0) { throw "Could not update Hermes plugins.enabled (exit code $exitCode)." }
}

$RequiredPaths = @(
    "plugin.yaml", "__init__.py", "gateway_isolation.py", "business_guard.py",
    "dashboard\manifest.json", "dashboard\plugin_api.py", "dashboard\plugin_api_core.py", "dashboard\extra_api.py",
    "dashboard\build_bundle.py", "dashboard\src\api.js", "dashboard\src\components.js", "dashboard\src\app.js",
    "dashboard\src\control_center_v2.js", "dashboard\src\control_cleanup.js", "dashboard\src\index.js",
    "doctor.ps1", "compatibility.py", "management\overview.py", "management\service.py", "task_center\service_v3.py",
    "providers\__init__.py", "providers\service.py", "resources\__init__.py", "resources\context.py",
    "resources\discovery.py", "resources\discovery_v2.py", "resources\registry.py", "resources\bindings.py", "resources\policy.py",
    "resources\tools.py", "resources\wechat_bound.py", "wechat\adapter.py", "wechat\runtime.py", "wechat\binding.py",
    "wechat\receiver.py", "wechat\sender.py", "wechat\state.py", "wechat\identity.py", "wechat\focus_guard.py", "wechat\discovery.py",
    "browser\__init__.py", "browser\discovery.py", "browser\binding.py", "browser\runtime.py",
    "hcc_gateway\__init__.py", "hcc_gateway\lifecycle.py", "hcc_gateway\routing.py", "requirements-windows.txt",
    "platforms\wechat-desktop\plugin.yaml", "platforms\wechat-desktop\adapter.py", "platforms\wechat-desktop\adapter_legacy.py"
)
foreach ($rel in $RequiredPaths) { $path = Join-Path $Source $rel; if (-not (Test-Path -LiteralPath $path)) { throw "Hermes Control Center package is incomplete: missing $path" } }
if (-not $HermesCommand) { throw "Hermes is not installed or is not on PATH." }
$Capabilities = [ordered]@{ plugins=$false; dashboard=$false; profile=$false; project=$false; cron=$false; kanban=$false }
foreach ($name in @("plugins","dashboard","profile","project","cron","kanban")) { $Capabilities[$name] = Test-HermesCapability -HermesExe $HermesCommand.Source -Command $name }
Write-Host "Hermes home: $HermesHome"
Write-Host "Detected Hermes capabilities:"
$Capabilities.GetEnumerator() | ForEach-Object { Write-Host ("  {0,-10} {1}" -f $_.Key, $_.Value) }
if (-not $Capabilities.profile) { throw "This Hermes build does not expose profile management; installation aborted." }
if (-not $Capabilities.plugins) { throw "This Hermes build does not expose plugin management; installation aborted." }
$HermesPython = Find-HermesPython
if (-not $HermesPython) { throw "Could not locate Hermes Python. Expected official venv under '$HermesHome\hermes-agent\venv' or a supported .venv/uv-tool layout." }
Write-Host "Hermes Python: $HermesPython"
if (-not $SkipDependencies) {
    Write-Host "Installing Control Center dependencies into Hermes Python..."
    $installed = $false
    try {
        & $HermesPython -m pip --version 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { $pipOutput = & $HermesPython -m pip install -r $Requirements 2>&1; $pipExit = $LASTEXITCODE; $pipOutput | ForEach-Object { Write-Host ([string]$_) }; if ($pipExit -eq 0) { $installed = $true } }
    } catch {}
    if (-not $installed) {
        $uv = Get-Command uv -ErrorAction SilentlyContinue
        if ($uv) {
            # Windows PowerShell 5.1 can surface native stderr as NativeCommandError when
            # $ErrorActionPreference is Stop. uv writes normal progress/status lines to stderr,
            # so temporarily relax error-action handling and decide success only by exit code.
            $previousErrorActionPreference = $ErrorActionPreference
            try {
                $ErrorActionPreference = "Continue"
                $uvOutput = & $uv.Source pip install --python $HermesPython -r $Requirements 2>&1
                $uvExit = $LASTEXITCODE
            } finally {
                $ErrorActionPreference = $previousErrorActionPreference
            }
            $uvOutput | ForEach-Object { Write-Host ([string]$_) }
            if ($uvExit -eq 0) { $installed = $true }
        }
    }
    if (-not $installed) { throw "Unable to install Control Center dependencies into Hermes Python." }
}
$PluginVersion = Read-PluginVersion (Join-Path $Source "plugin.yaml")
$RunningGatewayProfiles = @(Get-RunningGatewayProfiles)
$RunningDashboardPort = Get-RunningDashboardPort
New-Item -ItemType Directory -Force -Path $PluginsRoot | Out-Null
$TxnRoot = Join-Path $env:TEMP ("hermes-control-center-txn-" + [Guid]::NewGuid().ToString("N"))
$StagePlugin = Join-Path $TxnRoot "hermes-extensions"
$StagePlatform = Join-Path $TxnRoot "wechat-desktop"
$BackupPlugin = Join-Path $TxnRoot "backup-hermes-extensions"
$BackupPlatform = Join-Path $TxnRoot "backup-wechat-desktop"
$BackupLegacyNestedPlatform = Join-Path $TxnRoot "backup-legacy-nested-wechat-desktop"
try {
    Write-Host "Staging Hermes Control Center v$PluginVersion..."
    Write-Stage "Preparing clean staging directory outside Hermes plugins root"
    New-Item -ItemType Directory -Force -Path $StagePlugin | Out-Null
    Write-Stage "Copying runtime files only"; Copy-RuntimeTree -From $Source -To $StagePlugin
    Write-Stage "Copying WeChat platform adapter"; New-Item -ItemType Directory -Force -Path $StagePlatform | Out-Null
    Get-ChildItem -LiteralPath $PlatformSource -Force | ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination $StagePlatform -Recurse -Force }
    Write-Stage "Building Dashboard/Web bundle"
    $buildLog = Join-Path $TxnRoot "dashboard-build.log"
    & $HermesPython (Join-Path $StagePlugin "dashboard\build_bundle.py") --root (Join-Path $StagePlugin "dashboard") *> $buildLog
    $buildExit = $LASTEXITCODE
    if (Test-Path -LiteralPath $buildLog) { Get-Content -LiteralPath $buildLog | ForEach-Object { Write-Host ("     " + $_) } }
    if ($buildExit -ne 0) { throw "Dashboard/Web bundle build failed with exit code $buildExit. The build output is shown above." }
    Write-Stage "Dashboard/Web bundle complete"
    Write-Stage "Validating staged files"
    foreach ($required in @("plugin.yaml","__init__.py","gateway_isolation.py","business_guard.py","dashboard\manifest.json","dashboard\dist\index.js","dashboard\plugin_api.py","dashboard\plugin_api_core.py","dashboard\extra_api.py","providers\service.py","resources\context.py","resources\bindings.py","resources\policy.py","resources\tools.py","resources\wechat_bound.py","wechat\runtime.py","wechat\binding.py","wechat\receiver.py","wechat\sender.py","wechat\state.py","browser\runtime.py","hcc_gateway\lifecycle.py","hcc_gateway\routing.py")) {
        if (-not (Test-Path -LiteralPath (Join-Path $StagePlugin $required))) { throw "Staging validation failed: missing $required" }
    }
    foreach ($required in @("plugin.yaml","adapter.py","adapter_legacy.py")) { if (-not (Test-Path -LiteralPath (Join-Path $StagePlatform $required))) { throw "WeChat platform staging validation failed: missing $required" } }
    try {
        $manifest = Get-Content -LiteralPath (Join-Path $StagePlugin "dashboard\manifest.json") -Raw -Encoding UTF8 | ConvertFrom-Json
        $apiRel = [string]$manifest.api
        if (-not $apiRel -or -not (Test-Path -LiteralPath (Join-Path $StagePlugin ("dashboard\" + $apiRel)))) { throw "Dashboard manifest API target is missing: $apiRel" }
    } catch { throw "Dashboard manifest API validation failed: $($_.Exception.Message)" }
    Write-Stage "Compiling staged Python"
    $compileLog = Join-Path $TxnRoot "python-compile.log"
    & $HermesPython -m compileall -q $StagePlugin $StagePlatform *> $compileLog
    $compileExit = $LASTEXITCODE
    if ($compileExit -ne 0) { if (Test-Path -LiteralPath $compileLog) { Get-Content -LiteralPath $compileLog | ForEach-Object { Write-Host ("     " + $_) } }; throw "Python compile validation failed with exit code $compileExit." }
    Write-Stage "Python compile complete"
    Write-Stage "Installing staged files"
    if (Test-Path -LiteralPath $Target) { Move-Item -LiteralPath $Target -Destination $BackupPlugin -Force }
    if (Test-Path -LiteralPath $PlatformTarget) { Move-Item -LiteralPath $PlatformTarget -Destination $BackupPlatform -Force }
    if (Test-Path -LiteralPath $LegacyNestedPlatformTarget) { New-Item -ItemType Directory -Force -Path (Split-Path $BackupLegacyNestedPlatform -Parent) | Out-Null; Move-Item -LiteralPath $LegacyNestedPlatformTarget -Destination $BackupLegacyNestedPlatform -Force }
    Move-Item -LiteralPath $StagePlugin -Destination $Target -Force
    Move-Item -LiteralPath $StagePlatform -Destination $PlatformTarget -Force
    if (-not $NoEnable) { Write-Stage "Cleaning stale plugin enable entries and enabling current plugins"; Enable-ControlCenterPlugins -PythonExe $HermesPython -TempRoot $TxnRoot -ConfigFile $ConfigPath }
    else { Write-Stage "Plugin enable deferred by -NoEnable" }
    if (-not $NoEnable) { Write-Stage "Running installed doctor"; & (Join-Path $Target "doctor.ps1") -Installed; if ($LASTEXITCODE -ne 0) { throw "Installed doctor verification failed with exit code $LASTEXITCODE." } }
    Write-Stage "Refreshing independent Gateway profile runtime"
    Refresh-IsolatedProfileRuntime -PythonExe $HermesPython -TempRoot $TxnRoot
    Restart-PreviouslyRunningRuntime -GatewayProfiles $RunningGatewayProfiles -DashboardPort $RunningDashboardPort
    Write-Host "Hermes Control Center v$PluginVersion install complete." -ForegroundColor Green
} catch {
    Write-Warning "Installation failed; restoring previous Control Center files."
    if (Test-Path -LiteralPath $Target) { Remove-Item -LiteralPath $Target -Recurse -Force -ErrorAction SilentlyContinue }
    if (Test-Path -LiteralPath $PlatformTarget) { Remove-Item -LiteralPath $PlatformTarget -Recurse -Force -ErrorAction SilentlyContinue }
    if (Test-Path -LiteralPath $BackupPlugin) { Move-Item -LiteralPath $BackupPlugin -Destination $Target -Force }
    if (Test-Path -LiteralPath $BackupPlatform) { Move-Item -LiteralPath $BackupPlatform -Destination $PlatformTarget -Force }
    if (Test-Path -LiteralPath $BackupLegacyNestedPlatform) {
        New-Item -ItemType Directory -Force -Path (Split-Path $LegacyNestedPlatformTarget -Parent) | Out-Null
        Move-Item -LiteralPath $BackupLegacyNestedPlatform -Destination $LegacyNestedPlatformTarget -Force
    }
    throw
} finally {
    if (Test-Path -LiteralPath $TxnRoot) { Remove-Item -LiteralPath $TxnRoot -Recurse -Force -ErrorAction SilentlyContinue }
}
