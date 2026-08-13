param()

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$manifestPath = Join-Path $root "dashboard\manifest.json"
if (-not (Test-Path -LiteralPath $manifestPath)) { exit 0 }
$manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$manifest.api = "plugin_api.py"
$pluginYaml = Join-Path $root "plugin.yaml"
if (Test-Path -LiteralPath $pluginYaml) {
    $text = Get-Content -LiteralPath $pluginYaml -Raw -Encoding UTF8
    if ($text -match '(?m)^version:\s*["'']?([^\s"'']+)["'']?\s*$') { $manifest.version = $Matches[1].Trim() }
}
$manifest | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
