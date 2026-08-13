param()

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$pluginYaml = Join-Path $root "plugin.yaml"
$version = ""
if (Test-Path -LiteralPath $pluginYaml) {
    $text = Get-Content -LiteralPath $pluginYaml -Raw -Encoding UTF8
    if ($text -match '(?m)^version:\s*["'']?([^\s"'']+)["'']?\s*$') { $version = $Matches[1].Trim() }
}

function Normalize-Manifest([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return }
    $manifest = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
    $manifest.api = "plugin_api.py"
    if ($version) { $manifest.version = $version }
    $manifest | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $Path -Encoding UTF8
    $verify = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([string]$verify.api -ne "plugin_api.py") { throw "Dashboard manifest API normalization failed: $Path" }
}

Normalize-Manifest (Join-Path $root "dashboard\manifest.json")
$hermesHome = if ($env:HERMES_HOME) { $env:HERMES_HOME } elseif ($env:LOCALAPPDATA) { Join-Path $env:LOCALAPPDATA "hermes" } else { Join-Path $HOME ".hermes" }
Normalize-Manifest (Join-Path $hermesHome "plugins\hermes-extensions\dashboard\manifest.json")
