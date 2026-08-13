param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Inner = Join-Path $Root "Dashboard-Launch-v4.ps1"
$HermesHome = if ($env:HERMES_HOME) { $env:HERMES_HOME } elseif ($env:LOCALAPPDATA -and (Test-Path (Join-Path $env:LOCALAPPDATA "hermes"))) { Join-Path $env:LOCALAPPDATA "hermes" } else { Join-Path $HOME ".hermes" }
$env:HERMES_HOME = $HermesHome

if (-not (Test-Path -LiteralPath $Inner)) { throw "Missing Dashboard-Launch-v4.ps1" }

# Windows PowerShell 5.1 does not support Invoke-WebRequest -SkipHttpErrorCheck.
# Keep the v4 launcher logic unchanged while accepting that switch here.
function Invoke-WebRequest {
    param(
        [Parameter(Mandatory=$true)][string]$Uri,
        [switch]$UseBasicParsing,
        [switch]$SkipHttpErrorCheck,
        [int]$TimeoutSec = 0
    )
    $args = @{ Uri = $Uri; ErrorAction = "Stop" }
    if ($UseBasicParsing) { $args.UseBasicParsing = $true }
    if ($TimeoutSec -gt 0) { $args.TimeoutSec = $TimeoutSec }
    Microsoft.PowerShell.Utility\Invoke-WebRequest @args
}

Write-Host "Hermes home: $HermesHome"
& $Inner
$code = $LASTEXITCODE
if ($null -eq $code) { $code = 0 }
exit [int]$code
