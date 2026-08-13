param()

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$pluginYaml = Join-Path $root "plugin.yaml"
$version = ""
if (Test-Path -LiteralPath $pluginYaml) {
    $text = Get-Content -LiteralPath $pluginYaml -Raw -Encoding UTF8
    if ($text -match '(?m)^version:\s*["'']?([^\s"'']+)["'']?\s*$') { $version = $Matches[1].Trim() }
}

function Write-Utf8NoBom([string]$Path, [string]$Text) {
    $encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Text, $encoding)
}

function Normalize-Manifest([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return }
    $raw = [System.IO.File]::ReadAllText($Path)
    $manifest = $raw | ConvertFrom-Json
    $manifest.api = "plugin_api.py"
    if ($version) { $manifest.version = $version }
    $json = $manifest | ConvertTo-Json -Depth 20
    Write-Utf8NoBom -Path $Path -Text $json
    $bytes = [System.IO.File]::ReadAllBytes($Path)
    if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
        throw "Dashboard manifest still contains a UTF-8 BOM: $Path"
    }
    $verify = [System.IO.File]::ReadAllText($Path) | ConvertFrom-Json
    if ([string]$verify.api -ne "plugin_api.py") { throw "Dashboard manifest API normalization failed: $Path" }
}

$hermesHome = if ($env:HERMES_HOME) { $env:HERMES_HOME } elseif ($env:LOCALAPPDATA) { Join-Path $env:LOCALAPPDATA "hermes" } else { Join-Path $HOME ".hermes" }
$pluginsRoot = Join-Path $hermesHome "plugins"
if (Test-Path -LiteralPath $pluginsRoot) {
    Get-ChildItem -LiteralPath $pluginsRoot -Directory -Force -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like ".hermes-control-center-txn-*" } |
        ForEach-Object {
            Write-Host ("Removing stale Control Center transaction directory: " + $_.FullName) -ForegroundColor Yellow
            Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction SilentlyContinue
        }
}

Normalize-Manifest (Join-Path $root "dashboard\manifest.json")
Normalize-Manifest (Join-Path $hermesHome "plugins\hermes-extensions\dashboard\manifest.json")
