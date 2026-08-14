param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Inner = Join-Path $Root "Dashboard-Launch-v4.ps1"
$Probe = Join-Path $Root "Dashboard-Api-Probe.ps1"
$HermesHome = if ($env:HERMES_HOME) { $env:HERMES_HOME } elseif ($env:LOCALAPPDATA -and (Test-Path (Join-Path $env:LOCALAPPDATA "hermes"))) { Join-Path $env:LOCALAPPDATA "hermes" } else { Join-Path $HOME ".hermes" }
$env:HERMES_HOME = $HermesHome
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:HCC_FORCE_FRESH_DASHBOARD_PROBE = "1"

if (-not (Test-Path -LiteralPath $Inner)) { throw "Missing Dashboard-Launch-v4.ps1" }

function Get-ServedDashboardToken {
    param([Parameter(Mandatory=$true)][string]$ApiUri,[int]$TimeoutSec = 3)
    try {
        $parsed = [System.Uri]$ApiUri
        $root = "{0}://{1}:{2}/" -f $parsed.Scheme, $parsed.Host, $parsed.Port
        $html = Microsoft.PowerShell.Utility\Invoke-WebRequest -Uri $root -UseBasicParsing -TimeoutSec $TimeoutSec -ErrorAction Stop
        $text = [string]$html.Content
        $match = [regex]::Match($text, 'window\.__HERMES_SESSION_TOKEN__\s*=\s*(?<json>"(?:\\.|[^"\\])*")')
        if (-not $match.Success) { return "" }
        try { return [string]($match.Groups['json'].Value | ConvertFrom-Json) } catch { return "" }
    } catch { return "" }
}

function Invoke-WebRequest {
    param(
        [Parameter(Mandatory=$true)][string]$Uri,
        [switch]$UseBasicParsing,
        [switch]$SkipHttpErrorCheck,
        [int]$TimeoutSec = 0
    )

    if ($env:HCC_FORCE_FRESH_DASHBOARD_PROBE -eq "1" -and $Uri -match '/api/plugins/hermes-extensions/capabilities(?:\?|$)') {
        $env:HCC_FORCE_FRESH_DASHBOARD_PROBE = "0"
        return [pscustomobject]@{ StatusCode = 404; Content = '{"detail":"fresh restart requested"}' }
    }

    $args = @{ Uri = $Uri; ErrorAction = "Stop" }
    if ($UseBasicParsing) { $args.UseBasicParsing = $true }
    if ($TimeoutSec -gt 0) { $args.TimeoutSec = $TimeoutSec }
    try {
        return Microsoft.PowerShell.Utility\Invoke-WebRequest @args
    } catch [System.Net.WebException] {
        $response = $_.Exception.Response
        if ($response) {
            $status = [int]$response.StatusCode
            if ($status -eq 401 -and $Uri -match '/api/plugins/hermes-extensions/capabilities(?:\?|$)') {
                $token = Get-ServedDashboardToken -ApiUri $Uri -TimeoutSec $(if ($TimeoutSec -gt 0) { $TimeoutSec } else { 3 })
                if ($token) {
                    $retry = @{ Uri = $Uri; ErrorAction = "Stop"; Headers = @{ "X-Hermes-Session-Token" = $token } }
                    if ($UseBasicParsing) { $retry.UseBasicParsing = $true }
                    if ($TimeoutSec -gt 0) { $retry.TimeoutSec = $TimeoutSec }
                    return Microsoft.PowerShell.Utility\Invoke-WebRequest @retry
                }
                return [pscustomobject]@{ StatusCode = 401; Content = '{"detail":"Unauthorized"}' }
            }
        }
        throw
    }
}

Write-Host "Hermes home: $HermesHome"
try {
    & $Inner
    $code = $LASTEXITCODE
    if ($null -eq $code) { $code = 0 }
} catch {
    $code = 1
    Write-Host ("Dashboard launch error: " + $_.Exception.Message) -ForegroundColor Red
}

if ($code -ne 0 -and (Test-Path -LiteralPath $Probe)) {
    try {
        & $Probe -Port 9119
    } catch {
        Write-Host ("Exact API probe failed: " + $_.Exception.Message) -ForegroundColor Yellow
    }
}

exit [int]$code
