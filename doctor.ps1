param(
    [switch]$Preflight,
    [switch]$Installed,
    [switch]$Json
)

$ErrorActionPreference = "Continue"
Set-StrictMode -Version Latest
if (-not $Preflight -and -not $Installed) { $Installed = $true }
if ($Preflight -and $Installed) { throw "Choose either -Preflight or -Installed, not both." }

function Find-HermesPython([string]$HermesHome) {
    foreach ($candidate in @(
        (Join-Path $HermesHome "hermes-agent\venv\Scripts\python.exe"),
        (Join-Path $HermesHome "hermes-agent\.venv\Scripts\python.exe"),
        (Join-Path $HermesHome "venv\Scripts\python.exe"),
        (Join-Path $HermesHome ".venv\Scripts\python.exe")
    )) {
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if ($uv) {
        try {
            $toolDir = (& $uv.Source tool dir 2>$null | Select-Object -First 1).Trim()
            $candidate = Join-Path $toolDir "hermes-agent\Scripts\python.exe"
            if (Test-Path -LiteralPath $candidate) { return $candidate }
        } catch {}
    }
    return $null
}

function Read-PluginLists([string]$Python,[string]$ConfigPath) {
    $result = @{ enabled=@(); disabled=@() }
    if (-not $Python -or -not (Test-Path -LiteralPath $ConfigPath)) { return $result }
    try {
        $code = "import sys,yaml,json; c=yaml.safe_load(open(sys.argv[1],encoding='utf-8')) or {}; p=(c.get('plugins') or {}); print(json.dumps({'enabled':p.get('enabled') or [],'disabled':p.get('disabled') or []}))"
        $raw = (& $Python -c $code $ConfigPath 2>$null | Out-String).Trim()
        if ($raw) {
            $obj = $raw | ConvertFrom-Json
            $result.enabled = @($obj.enabled)
            $result.disabled = @($obj.disabled)
        }
    } catch {}
    return $result
}

function Test-Utf8Bom([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return $false }
    $bytes = [System.IO.File]::ReadAllBytes($Path)
    return ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF)
}

$HermesHome = if ($env:HERMES_HOME) { $env:HERMES_HOME } elseif ($env:LOCALAPPDATA -and (Test-Path (Join-Path $env:LOCALAPPDATA "hermes"))) { Join-Path $env:LOCALAPPDATA "hermes" } else { Join-Path $HOME ".hermes" }
$env:HERMES_HOME = $HermesHome
$Hermes = Get-Command hermes -ErrorAction SilentlyContinue
$HermesPython = Find-HermesPython $HermesHome
$ConfigPath = Join-Path $HermesHome "config.yaml"
$Report = [ordered]@{
    mode = if ($Preflight) { "preflight" } else { "installed" }
    hermes_on_path = [bool]$Hermes
    hermes_home = $HermesHome
    hermes_python = if ($HermesPython) { $HermesPython } else { "" }
    python_found = [bool]$HermesPython
}

if ($Hermes) {
    try { $Report.version = (& $Hermes.Source --version 2>&1 | Out-String).Trim() } catch { $Report.version = "unknown" }
} else { $Report.version = "unavailable" }

if ($HermesPython) {
    try { & $HermesPython -c "import yaml, croniter" 2>$null | Out-Null; $Report.shared_dependencies = ($LASTEXITCODE -eq 0) } catch { $Report.shared_dependencies = $false }
    try { & $HermesPython -c "import pywinauto, pyperclip" 2>$null | Out-Null; $Report.wechat_dependencies = ($LASTEXITCODE -eq 0) } catch { $Report.wechat_dependencies = $false }
} else {
    $Report.shared_dependencies = $false
    $Report.wechat_dependencies = $false
}

$Warnings = New-Object System.Collections.Generic.List[string]
$Errors = New-Object System.Collections.Generic.List[string]
if (-not $Report.hermes_on_path) { $Errors.Add("Hermes executable is not on PATH.") }
if (-not $Report.python_found) { $Errors.Add("Hermes Python interpreter could not be located.") }
if (-not $Report.shared_dependencies) { $Warnings.Add("Shared Control Center Python dependencies are not installed yet.") }
if (-not $Report.wechat_dependencies) { $Warnings.Add("Windows WeChat Python dependencies are not installed yet.") }

if ($Installed) {
    $PluginRoot = Join-Path $HermesHome "plugins\hermes-extensions"
    $ManifestPath = Join-Path $PluginRoot "dashboard\manifest.json"
    $SmokePath = Join-Path $PluginRoot "dashboard\api_smoke.py"
    $required = [ordered]@{
        plugin_manifest = "plugin.yaml"
        plugin_entry = "__init__.py"
        dashboard_manifest = "dashboard\manifest.json"
        dashboard_bundle = "dashboard\dist\index.js"
        dashboard_api_entry = "dashboard\plugin_api.py"
        dashboard_api_v2 = "dashboard\plugin_api_v2.py"
        dashboard_api_smoke = "dashboard\api_smoke.py"
        management_service = "management\service.py"
        task_service_v3 = "task_center\service_v3.py"
        provider_service = "providers\service.py"
        resource_registry = "resources\registry.py"
        resource_bindings = "resources\bindings.py"
        resource_policy = "resources\policy.py"
        resource_tools = "resources\tools.py"
        wechat_runtime = "wechat\runtime.py"
    }
    foreach ($item in $required.GetEnumerator()) {
        $Report[$item.Key] = Test-Path -LiteralPath (Join-Path $PluginRoot $item.Value)
        if (-not $Report[$item.Key]) { $Errors.Add("Installed component missing: $($item.Value)") }
    }

    $Report.dashboard_manifest_bom = Test-Utf8Bom $ManifestPath
    if ($Report.dashboard_manifest_bom) { $Errors.Add("Dashboard manifest contains a UTF-8 BOM.") }

    try {
        $manifest = [System.IO.File]::ReadAllText($ManifestPath) | ConvertFrom-Json
        $Report.dashboard_manifest_api_target = [string]$manifest.api
        $Report.dashboard_manifest_version = [string]$manifest.version
        $Report.dashboard_manifest_api_exists = [bool]($manifest.api -and (Test-Path -LiteralPath (Join-Path $PluginRoot ("dashboard\" + [string]$manifest.api))))
        if ([string]$manifest.api -ne "plugin_api.py") { $Errors.Add("Dashboard manifest API must be plugin_api.py.") }
        if (-not $Report.dashboard_manifest_api_exists) { $Errors.Add("Dashboard manifest API target does not exist.") }
    } catch {
        $Report.dashboard_manifest_api_target = ""
        $Report.dashboard_manifest_api_exists = $false
        $Errors.Add("Dashboard manifest could not be parsed: $($_.Exception.Message)")
    }

    $Report.dashboard_api_importable = $false
    $Report.dashboard_api_smoke_output = ""
    if ($HermesPython -and (Test-Path -LiteralPath $SmokePath)) {
        try {
            $output = (& $HermesPython $SmokePath 2>&1 | Out-String).Trim()
            $Report.dashboard_api_smoke_output = $output
            $Report.dashboard_api_importable = ($LASTEXITCODE -eq 0)
        } catch { $Report.dashboard_api_smoke_output = $_.Exception.Message }
    }
    if (-not $Report.dashboard_api_importable) { $Errors.Add("Dashboard API smoke import failed.") }

    $state = Read-PluginLists $HermesPython $ConfigPath
    $Report.plugins_enabled_entries = ($state.enabled -join ", ")
    $Report.plugins_disabled_entries = ($state.disabled -join ", ")
    $Report.plugin_enabled = [bool]($state.enabled -contains "hermes-extensions")
    $Report.plugin_disabled = [bool]($state.disabled -contains "hermes-extensions")
    $Report.legacy_wechat_enabled = [bool]($state.enabled -contains "wechat-desktop")
    $Report.legacy_wechat_directory = Test-Path -LiteralPath (Join-Path $HermesHome "plugins\wechat-desktop")
    if (-not $Report.plugin_enabled) { $Errors.Add("hermes-extensions is not enabled.") }
    if ($Report.plugin_disabled) { $Errors.Add("hermes-extensions is still disabled.") }
    if ($Report.legacy_wechat_enabled -or $Report.legacy_wechat_directory) {
        $Warnings.Add("Legacy standalone wechat-desktop is still present during this install stage; Setup finalize will remove it.")
    }
}

$Report.warnings = @($Warnings)
$Report.errors = @($Errors)
$Report.ok = ($Errors.Count -eq 0)

if ($Json) {
    $Report | ConvertTo-Json -Depth 6
} else {
    Write-Host "Hermes Control Center doctor ($($Report.mode))"
    Write-Host "----------------------------------------"
    $Report.GetEnumerator() | Where-Object { $_.Key -notin @("warnings","errors") } | ForEach-Object { Write-Host ("{0,-32} {1}" -f $_.Key, $_.Value) }
    foreach ($message in $Warnings) { Write-Warning $message }
    foreach ($message in $Errors) { Write-Error $message }
}
if ($Errors.Count -gt 0) { exit 2 }
exit 0
