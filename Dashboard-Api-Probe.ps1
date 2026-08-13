param([int]$Port = 9119)

$ErrorActionPreference = "Continue"
$HermesHome = if ($env:HERMES_HOME) { $env:HERMES_HOME } elseif ($env:LOCALAPPDATA) { Join-Path $env:LOCALAPPDATA "hermes" } else { Join-Path $HOME ".hermes" }

function Invoke-Probe([string]$Url) {
    $response = $null
    $reader = $null
    try {
        $request = [System.Net.HttpWebRequest]::Create($Url)
        $request.Method = "GET"
        $request.Timeout = 5000
        $request.ReadWriteTimeout = 5000
        $request.AllowAutoRedirect = $false
        $response = $request.GetResponse()
        $status = [int]$response.StatusCode
        $reader = New-Object System.IO.StreamReader($response.GetResponseStream())
        $body = $reader.ReadToEnd()
        return [pscustomobject]@{ status=$status; body=$body; error="" }
    } catch [System.Net.WebException] {
        $status = 0
        $body = ""
        $webResponse = $_.Exception.Response
        if ($webResponse) {
            try {
                $status = [int]$webResponse.StatusCode
                $reader = New-Object System.IO.StreamReader($webResponse.GetResponseStream())
                $body = $reader.ReadToEnd()
            } catch {}
        }
        return [pscustomobject]@{ status=$status; body=$body; error=$_.Exception.Message }
    } catch {
        return [pscustomobject]@{ status=0; body=""; error=$_.Exception.Message }
    } finally {
        if ($reader) { try { $reader.Dispose() } catch {} }
        if ($response) { try { $response.Dispose() } catch {} }
    }
}

Write-Host ""
Write-Host "Exact Control Center API diagnostics" -ForegroundColor Yellow
Write-Host "------------------------------------" -ForegroundColor Yellow

$capUrl = "http://127.0.0.1:$Port/api/plugins/hermes-extensions/capabilities"
$cap = Invoke-Probe $capUrl
Write-Host ("Capabilities HTTP: " + $cap.status)
if ($cap.body) { Write-Host "Capabilities response:"; Write-Host $cap.body }
if ($cap.error) { Write-Host ("Capabilities request error: " + $cap.error) }

$pluginsUrl = "http://127.0.0.1:$Port/api/dashboard/plugins"
$plugins = Invoke-Probe $pluginsUrl
Write-Host ("Plugin discovery HTTP: " + $plugins.status)
if ($plugins.body) { Write-Host "Plugin discovery response:"; Write-Host $plugins.body }
if ($plugins.error) { Write-Host ("Plugin discovery request error: " + $plugins.error) }

$errorsLog = Join-Path $HermesHome "logs\errors.log"
if (Test-Path -LiteralPath $errorsLog) {
    Write-Host ""
    Write-Host "Last 120 lines of Hermes errors.log:" -ForegroundColor Yellow
    Get-Content -LiteralPath $errorsLog -Tail 120 -ErrorAction SilentlyContinue | ForEach-Object { Write-Host $_ }
} else {
    Write-Host "Hermes errors.log not found: $errorsLog"
}

Write-Host "------------------------------------" -ForegroundColor Yellow
