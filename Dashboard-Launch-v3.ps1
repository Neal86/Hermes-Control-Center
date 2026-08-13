param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Inner = Join-Path $Root "Dashboard-Launch-v2.ps1"
$HermesHome = if ($env:HERMES_HOME) { $env:HERMES_HOME } elseif ($env:LOCALAPPDATA -and (Test-Path (Join-Path $env:LOCALAPPDATA "hermes"))) { Join-Path $env:LOCALAPPDATA "hermes" } else { Join-Path $HOME ".hermes" }
$env:HERMES_HOME = $HermesHome

if (-not (Test-Path -LiteralPath $Inner)) { throw "Missing Dashboard-Launch-v2.ps1" }
Write-Host "Hermes home: $HermesHome"
& powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File $Inner
$code = $LASTEXITCODE
if ($null -eq $code) { $code = 1 }
exit [int]$code
