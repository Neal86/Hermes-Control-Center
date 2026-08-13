param(
    [ValidateSet("Install", "UpdateHermes", "UpdatePlugin", "Repair", "Dashboard")]
    [string]$Action
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$SetupScript = Join-Path $Root "Setup-Hermes-Control-Center.ps1"

if (-not (Test-Path -LiteralPath $SetupScript)) { throw "Missing Setup-Hermes-Control-Center.ps1" }

# The persistent V4 menu owns all interaction. Suppress nested prompts and
# automatic dashboard launches in the one-shot core action.
$args = @("-Action", $Action, "-NoPrompt", "-NoDashboard")
& powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File $SetupScript @args
$code = $LASTEXITCODE
if ($null -eq $code) { $code = 1 }
exit [int]$code
