param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Next = Join-Path $Root "Dashboard-Launch-v4.ps1"
if (-not (Test-Path -LiteralPath $Next)) { throw "Missing Dashboard-Launch-v4.ps1" }

& powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File $Next
$code = $LASTEXITCODE
if ($null -eq $code) { $code = 1 }
exit [int]$code
