param(
    [switch]$Preflight,
    [switch]$Installed,
    [switch]$Json
)

$ErrorActionPreference = "Continue"
Set-StrictMode -Version Latest
if (-not $Preflight -and -not $Installed) { $Installed = $true }
if ($Preflight -and $Installed) { throw "Choose either -Preflight or -Installed, not both." }

function Test-HermesCapability {
    param([string]$HermesExe, [string]$Command)
    try {
        $output = & $HermesExe $Command --help 2>&1 | Out-String
        if ($output -match "invalid choice|no such command|unknown command") { return $false }
        return $LASTEXITCODE -eq 0
    } catch { return $false }
}

function Find-HermesPython {
    param([object]$HermesCommand, [string]$HermesHome)
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
            $text = & $HermesCommand.Source --version 2>&1 | Out-String
            if ($text -match "(?m)^Project:\s*(.+?)\s*$") {
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
    foreach ($candidate in $candidates | Select-Object -Unique) {
        if (-not (Test-Path -LiteralPath $candidate)) { continue }
        try { & $candidate -c "import sys; print(sys.executable)" 2>$null | Out-Null; if ($LASTEXITCODE -eq 0) { return $candidate } } catch {}
    }
    return $null
}

function Read-EnabledPlugins {
    param([string]$PythonExe, [string]$Path)
    if (-not $PythonExe -or -not (Test-Path -LiteralPath $Path)) { return @() }
    try {
        $lines = & $PythonExe -c "import sys,yaml; c=yaml.safe_load(open(sys.argv[1],encoding='utf-8')) or {}; v=((c.get('plugins') or {}).get('enabled') or []); [print(str(x)) for x in v if str(x).strip()]" $Path 2>$null
        $items = New-Object System.Collections.Generic.List[string]
        foreach ($line in @($lines)) { $value = ([string]$line).Trim(); if ($value) { $items.Add($value) } }
        return @($items.ToArray())
    } catch { return @() }
}

$HermesHome = if ($env:HERMES_HOME) { $env:HERMES_HOME } elseif ($env:LOCALAPPDATA -and (Test-Path (Join-Path $env:LOCALAPPDATA "hermes"))) { Join-Path $env:LOCALAPPDATA "hermes" } else { Join-Path $HOME ".hermes" }
$env:HERMES_HOME = $HermesHome
$ConfigPath = Join-Path $HermesHome "config.yaml"
$Hermes = Get-Command hermes -ErrorAction SilentlyContinue
$HermesPython = Find-HermesPython -HermesCommand $Hermes -HermesHome $HermesHome
$Report = [ordered]@{
    mode = if ($Preflight) { "preflight" } else { "installed" }
    hermes_on_path = [bool]$Hermes
    hermes_home = $HermesHome
    hermes_python = if ($HermesPython) { $HermesPython } else { "" }
    python_found = [bool]$HermesPython
}

if ($Hermes) {
    foreach ($name in @("plugins", "dashboard", "profile", "project", "cron", "kanban")) { $Report["capability_$name"] = Test-HermesCapability -HermesExe $Hermes.Source -Command $name }
    try { $Report["version"] = (& $Hermes.Source --version 2>&1 | Out-String).Trim() } catch { $Report["version"] = "unknown" }
} else {
    foreach ($name in @("plugins", "dashboard", "profile", "project", "cron", "kanban")) { $Report["capability_$name"] = $false }
    $Report["version"] = "unavailable"
}

if ($HermesPython) {
    try { & $HermesPython -c "import yaml, croniter" 2>$null | Out-Null; $Report["shared_dependencies"] = $LASTEXITCODE -eq 0 } catch { $Report["shared_dependencies"] = $false }
    try { & $HermesPython -c "import pywinauto, pyperclip" 2>$null | Out-Null; $Report["wechat_dependencies"] = $LASTEXITCODE -eq 0 } catch { $Report["wechat_dependencies"] = $false }
} else {
    $Report["shared_dependencies"] = $false
    $Report["wechat_dependencies"] = $false
}

if ($Installed) {
    $PluginRoot = Join-Path $HermesHome "plugins\hermes-extensions"
    $PlatformRoot = Join-Path $HermesHome "plugins\wechat-desktop"
    $InstalledFiles = [ordered]@{
        plugin_manifest = "plugin.yaml"
        plugin_entry = "__init__.py"
        dashboard_manifest = "dashboard\manifest.json"
        dashboard_bundle = "dashboard\dist\index.js"
        dashboard_api_entry = "dashboard\plugin_api.py"
        dashboard_api_core = "dashboard\plugin_api_core.py"
        dashboard_api_extra = "dashboard\extra_api.py"
        management_overview = "management\overview.py"
        management_service = "management\service.py"
        task_service_v3 = "task_center\service_v3.py"
        provider_service = "providers\service.py"
        resource_context = "resources\context.py"
        resource_discovery = "resources\discovery.py"
        resource_registry = "resources\registry.py"
        resource_bindings = "resources\bindings.py"
        resource_policy = "resources\policy.py"
        resource_tools = "resources\tools.py"
        resource_wechat_bound = "resources\wechat_bound.py"
        wechat_runtime = "wechat\runtime.py"
    }
    foreach ($entry in $InstalledFiles.GetEnumerator()) { $Report[$entry.Key] = Test-Path -LiteralPath (Join-Path $PluginRoot $entry.Value) }
    $Report["wechat_platform_manifest"] = Test-Path -LiteralPath (Join-Path $PlatformRoot "plugin.yaml")
    $Report["wechat_platform_adapter"] = Test-Path -LiteralPath (Join-Path $PlatformRoot "adapter.py")
    $Report["wechat_platform_legacy"] = Test-Path -LiteralPath (Join-Path $PlatformRoot "adapter_legacy.py")

    $enabled = @(Read-EnabledPlugins -PythonExe $HermesPython -Path $ConfigPath)
    $Report["plugins_enabled_entries"] = if ($enabled.Count) { $enabled -join ", " } else { "" }
    $Report["plugin_enabled"] = [bool]($enabled | Where-Object { $_ -eq "hermes-extensions" })
    $Report["wechat_plugin_enabled"] = [bool]($enabled | Where-Object { $_ -eq "wechat-desktop" })

    try {
        $manifest = Get-Content -LiteralPath (Join-Path $PluginRoot "dashboard\manifest.json") -Raw -Encoding UTF8 | ConvertFrom-Json
        $apiRel = [string]$manifest.api
        $Report["dashboard_manifest_api_target"] = $apiRel
        $Report["dashboard_manifest_api_exists"] = [bool]($apiRel -and (Test-Path -LiteralPath (Join-Path $PluginRoot ("dashboard\" + $apiRel))))
    } catch {
        $Report["dashboard_manifest_api_target"] = ""
        $Report["dashboard_manifest_api_exists"] = $false
    }
}

$Warnings = New-Object System.Collections.Generic.List[string]
$Errors = New-Object System.Collections.Generic.List[string]
if (-not $Report.hermes_on_path) { $Errors.Add("Hermes executable is not on PATH.") }
if (-not $Report.python_found) { $Errors.Add("Hermes Python interpreter could not be located safely.") }
if ($Report.hermes_on_path -and -not $Report.capability_profile) { $Errors.Add("Hermes profile capability is required.") }
if ($Report.hermes_on_path -and -not $Report.capability_plugins) { $Errors.Add("Hermes plugin capability is required.") }
if (-not $Report.capability_project) { $Warnings.Add("Native Projects are unavailable; the rest of Control Center remains supported.") }
if (-not $Report.shared_dependencies) { $Warnings.Add("Shared plugin Python dependencies are not installed yet.") }
if (-not $Report.wechat_dependencies) { $Warnings.Add("Windows WeChat Python dependencies are not installed yet.") }

if ($Installed) {
    foreach ($key in @(
        "plugin_manifest", "plugin_entry", "dashboard_manifest", "dashboard_bundle",
        "dashboard_api_entry", "dashboard_api_core", "dashboard_api_extra",
        "management_overview", "management_service", "task_service_v3", "provider_service",
        "resource_context", "resource_discovery", "resource_registry", "resource_bindings",
        "resource_policy", "resource_tools", "resource_wechat_bound", "wechat_runtime",
        "wechat_platform_manifest", "wechat_platform_adapter", "wechat_platform_legacy", "dashboard_manifest_api_exists"
    )) { if (-not $Report[$key]) { $Errors.Add("Installed component missing or invalid: $key") } }
    if (-not $Report.plugin_enabled) { $Errors.Add("hermes-extensions is not present in plugins.enabled in $ConfigPath.") }
    if (-not $Report.wechat_plugin_enabled) { $Errors.Add("wechat-desktop is not present in plugins.enabled in $ConfigPath.") }
}

$Report["warnings"] = @($Warnings)
$Report["errors"] = @($Errors)
$Report["ok"] = $Errors.Count -eq 0

if ($Json) { $Report | ConvertTo-Json -Depth 6 }
else {
    Write-Host "Hermes Control Center doctor ($($Report.mode))"
    Write-Host "----------------------------------------"
    $Report.GetEnumerator() | Where-Object { $_.Key -notin @("warnings", "errors") } | ForEach-Object { Write-Host ("{0,-32} {1}" -f $_.Key, $_.Value) }
    foreach ($message in $Warnings) { Write-Warning $message }
    foreach ($message in $Errors) { Write-Error $message }
}
if ($Errors.Count -gt 0) { exit 2 }
exit 0
