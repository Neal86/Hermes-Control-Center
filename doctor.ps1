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
    foreach ($base in @($env:APPDATA, $env:LOCALAPPDATA)) {
        if ($base) { $candidates.Add((Join-Path $base "uv\tools\hermes-agent\Scripts\python.exe")) }
    }
    if ($HermesCommand) {
        try {
            $text = & $HermesCommand.Source --version 2>&1 | Out-String
            if ($text -match "(?m)^Project:\s*(.+?)\s*$") {
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
        if (-not (Test-Path -LiteralPath $candidate)) { continue }
        try {
            & $candidate -c "import sys; print(sys.executable)" 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) { return $candidate }
        } catch {}
    }
    return $null
}

$HermesHome = if ($env:HERMES_HOME) { $env:HERMES_HOME } else { Join-Path $HOME ".hermes" }
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
    foreach ($name in @("plugins", "dashboard", "profile", "project", "cron", "kanban")) {
        $Report["capability_$name"] = Test-HermesCapability -HermesExe $Hermes.Source -Command $name
    }
    try { $Report["version"] = (& $Hermes.Source --version 2>&1 | Out-String).Trim() }
    catch { $Report["version"] = "unknown" }
} else {
    foreach ($name in @("plugins", "dashboard", "profile", "project", "cron", "kanban")) {
        $Report["capability_$name"] = $false
    }
    $Report["version"] = "unavailable"
}

if ($HermesPython) {
    try {
        & $HermesPython -c "import yaml, croniter" 2>$null | Out-Null
        $Report["shared_dependencies"] = $LASTEXITCODE -eq 0
    } catch { $Report["shared_dependencies"] = $false }
    try {
        & $HermesPython -c "import pywinauto, pyperclip" 2>$null | Out-Null
        $Report["wechat_dependencies"] = $LASTEXITCODE -eq 0
    } catch { $Report["wechat_dependencies"] = $false }
} else {
    $Report["shared_dependencies"] = $false
    $Report["wechat_dependencies"] = $false
}

if ($Installed) {
    $PluginRoot = Join-Path $HermesHome "plugins\hermes-extensions"
    $PlatformRoot = Join-Path $HermesHome "plugins\platforms\wechat-desktop"
    $Report["plugin_manifest"] = Test-Path -LiteralPath (Join-Path $PluginRoot "plugin.yaml")
    $Report["dashboard_manifest"] = Test-Path -LiteralPath (Join-Path $PluginRoot "dashboard\manifest.json")
    $Report["dashboard_bundle"] = Test-Path -LiteralPath (Join-Path $PluginRoot "dashboard\dist\index.js")
    $Report["dashboard_api"] = Test-Path -LiteralPath (Join-Path $PluginRoot "dashboard\plugin_api.py")
    $Report["management_overview"] = Test-Path -LiteralPath (Join-Path $PluginRoot "management\overview.py")
    $Report["task_service_v3"] = Test-Path -LiteralPath (Join-Path $PluginRoot "task_center\service_v3.py")
    $Report["wechat_runtime"] = Test-Path -LiteralPath (Join-Path $PluginRoot "wechat\runtime.py")
    $Report["wechat_platform"] = Test-Path -LiteralPath (Join-Path $PlatformRoot "plugin.yaml")
    if ($Hermes -and $Report.capability_plugins) {
        try {
            $pluginList = & $Hermes.Source plugins list --plain --no-bundled 2>&1 | Out-String
            $Report["plugin_detected"] = $pluginList -match "hermes-extensions"
            $Report["wechat_plugin_detected"] = $pluginList -match "wechat-desktop"
        } catch {
            $Report["plugin_detected"] = $false
            $Report["wechat_plugin_detected"] = $false
        }
    } else {
        $Report["plugin_detected"] = $false
        $Report["wechat_plugin_detected"] = $false
    }
    if ($Hermes -and $Report.capability_dashboard) {
        try {
            $dashboard = & $Hermes.Source dashboard --status 2>&1 | Out-String
            $Report["dashboard_running"] = $dashboard -notmatch "No hermes dashboard processes running"
        } catch { $Report["dashboard_running"] = $false }
    } else { $Report["dashboard_running"] = $false }
}

$Warnings = New-Object System.Collections.Generic.List[string]
$Errors = New-Object System.Collections.Generic.List[string]
if (-not $Report.hermes_on_path) { $Errors.Add("Hermes executable is not on PATH.") }
if (-not $Report.python_found) { $Errors.Add("Hermes Python interpreter could not be located safely.") }
if ($Report.hermes_on_path -and -not $Report.capability_profile) { $Errors.Add("Hermes profile capability is required.") }
if ($Report.hermes_on_path -and -not $Report.capability_plugins) { $Errors.Add("Hermes plugin capability is required.") }
if (-not $Report.capability_project) { $Warnings.Add("Native Projects are unavailable; Agents, Tasks, Dashboard and WeChat remain supported.") }
if (-not $Report.shared_dependencies) { $Warnings.Add("Shared plugin Python dependencies are not installed yet.") }
if (-not $Report.wechat_dependencies) { $Warnings.Add("Windows WeChat Python dependencies are not installed yet.") }

if ($Installed) {
    foreach ($key in @(
        "plugin_manifest", "dashboard_manifest", "dashboard_bundle", "dashboard_api",
        "management_overview", "task_service_v3", "wechat_runtime", "wechat_platform"
    )) {
        if (-not $Report[$key]) { $Errors.Add("Installed component missing: $key") }
    }
    if (-not $Report.plugin_detected) { $Errors.Add("Hermes does not discover hermes-extensions.") }
    if (-not $Report.wechat_plugin_detected) { $Errors.Add("Hermes does not discover wechat-desktop.") }
}

$Report["warnings"] = @($Warnings)
$Report["errors"] = @($Errors)
$Report["ok"] = $Errors.Count -eq 0

if ($Json) {
    $Report | ConvertTo-Json -Depth 6
} else {
    Write-Host "Hermes Extensions doctor ($($Report.mode))"
    Write-Host "-------------------------------------"
    $Report.GetEnumerator() | Where-Object { $_.Key -notin @("warnings", "errors") } | ForEach-Object {
        Write-Host ("{0,-28} {1}" -f $_.Key, $_.Value)
    }
    foreach ($message in $Warnings) { Write-Warning $message }
    foreach ($message in $Errors) { Write-Error $message }
}

if ($Errors.Count -gt 0) { exit 2 }
exit 0
