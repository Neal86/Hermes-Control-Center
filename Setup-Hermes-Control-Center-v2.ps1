param(
    [ValidateSet("Install", "UpdateHermes", "UpdatePlugin", "Repair", "Dashboard")]
    [string]$Action
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$LegacySetup = Join-Path $Root "Setup-Hermes-Control-Center.ps1"
$EnableScript = Join-Path $Root "Enable-Control-Center-Plugins.ps1"

if (-not (Test-Path -LiteralPath $LegacySetup)) { throw "Missing Setup-Hermes-Control-Center.ps1" }

$needsEnable = $Action -in @("Install", "UpdatePlugin", "Repair")
$args = @("-Action", $Action, "-NoPrompt", "-NoDashboard")
if ($needsEnable) { $args += "-NoEnable" }

& powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File $LegacySetup @args
$code = $LASTEXITCODE
if ($null -eq $code) { $code = 1 }
if ($code -ne 0) { exit $code }

if ($needsEnable) {
    if (-not (Test-Path -LiteralPath $EnableScript)) { throw "Missing Enable-Control-Center-Plugins.ps1" }
    & powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File $EnableScript
    $enableCode = $LASTEXITCODE
    if ($null -eq $enableCode) { $enableCode = 1 }
    if ($enableCode -ne 0) { exit $enableCode }
}

exit 0
