param(
    [int]$PreferredPort = 9119,
    [switch]$NoOpen
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$ProgressPreference = "SilentlyContinue"

$HostName = "127.0.0.1"
$TimeoutSeconds = 90
$HermesHome = if ($env:HERMES_HOME) { $env:HERMES_HOME } elseif ($env:LOCALAPPDATA) { Join-Path $env:LOCALAPPDATA "hermes" } else { Join-Path $HOME ".hermes" }
$env:HERMES_HOME = $HermesHome
$LogDir = Join-Path $HermesHome "logs\control-center"

function Test-LocalPort {
    param([int]$Port, [int]$TimeoutMs = 400)
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $async = $client.BeginConnect($HostName, $Port, $null, $null)
        if (-not $async.AsyncWaitHandle.WaitOne($TimeoutMs, $false)) { return $false }
        $client.EndConnect($async)
        return $client.Connected
    } catch { return $false } finally { $client.Close() }
}

function Test-ControlCenterApi {
    param([int]$Port)
    try {
        $url = "http://127.0.0.1:$Port/api/plugins/hermes-extensions/capabilities"
        $response = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 3
        return [int]$response.StatusCode -ne 404
    } catch {
        # Newer Hermes releases protect plugin APIs with dashboard auth. A
        # 401/403 proves that the route is mounted; only 404 or a connection
        # failure means Control Center is not ready.
        $errorResponse = $_.Exception.Response
        if ($errorResponse -and $null -ne $errorResponse.StatusCode) {
            return [int]$errorResponse.StatusCode -ne 404
        }
        return $false
    }
}

function Find-Hermes {
    foreach ($candidate in @(
        (Join-Path $HermesHome "bin\hermes.exe"),
        (Join-Path $HermesHome "hermes-agent\bin\hermes.exe")
    )) {
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    $cmd = Get-Command hermes -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

function Find-HermesAgentRoot {
    param([string]$HermesPath)
    $candidates = New-Object System.Collections.Generic.List[string]
    $candidates.Add((Join-Path $HermesHome "hermes-agent"))
    if ($HermesPath) {
        try {
            $binDir = Split-Path -Parent $HermesPath
            $candidates.Add((Split-Path -Parent $binDir))
        } catch {}
    }
    foreach ($candidate in $candidates) {
        if (-not $candidate) { continue }
        if ((Test-Path -LiteralPath (Join-Path $candidate "package.json")) -and
            (Test-Path -LiteralPath (Join-Path $candidate "web\package.json")) -and
            (Test-Path -LiteralPath (Join-Path $candidate "hermes_cli"))) {
            return $candidate
        }
    }
    return $null
}

function Find-Npm {
    $portable = Join-Path $HermesHome "runtime\node\npm.cmd"
    if (Test-Path -LiteralPath $portable) { return $portable }
    foreach ($name in @("npm.cmd", "npm")) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) { return $cmd.Source }
    }
    return $null
}

function Install-PortableNode {
    $arch = if ($env:PROCESSOR_ARCHITECTURE -eq "ARM64") { "arm64" } else { "x64" }
    $base = "https://nodejs.org/dist/latest-v22.x"
    $portableRoot = Join-Path $HermesHome "runtime\node"
    $tempRoot = Join-Path $env:TEMP ("hermes-node-" + [Guid]::NewGuid().ToString("N"))
    Write-Host "Node.js/npm is missing. Installing a private portable Node.js runtime for Hermes..." -ForegroundColor Yellow
    try {
        New-Item -ItemType Directory -Force -Path $tempRoot | Out-Null
        $sums = (Invoke-WebRequest -UseBasicParsing -Uri ($base + "/SHASUMS256.txt") -TimeoutSec 30).Content
        $match = [regex]::Match($sums, "(?m)^([0-9a-f]{64})  (node-v([0-9]+\.[0-9]+\.[0-9]+)-win-$arch\.zip)$")
        if (-not $match.Success) { throw "Could not resolve the official Node.js Windows $arch archive." }
        $expectedHash = $match.Groups[1].Value.ToLowerInvariant()
        $fileName = $match.Groups[2].Value
        $version = $match.Groups[3].Value
        $zip = Join-Path $tempRoot $fileName
        Invoke-WebRequest -UseBasicParsing -Uri ($base + "/" + $fileName) -OutFile $zip -TimeoutSec 120
        $actualHash = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actualHash -ne $expectedHash) { throw "Node.js download checksum verification failed." }
        $extract = Join-Path $tempRoot "extract"
        Expand-Archive -LiteralPath $zip -DestinationPath $extract -Force
        $source = Get-ChildItem -LiteralPath $extract -Directory | Select-Object -First 1
        if (-not $source) { throw "Downloaded Node.js archive did not contain the expected folder." }
        Remove-Item -LiteralPath $portableRoot -Recurse -Force -ErrorAction SilentlyContinue
        New-Item -ItemType Directory -Force -Path $portableRoot | Out-Null
        Get-ChildItem -LiteralPath $source.FullName -Force | ForEach-Object { Move-Item -LiteralPath $_.FullName -Destination $portableRoot -Force }
        $npm = Join-Path $portableRoot "npm.cmd"
        $node = Join-Path $portableRoot "node.exe"
        if (-not (Test-Path -LiteralPath $npm) -or -not (Test-Path -LiteralPath $node)) { throw "Portable Node.js installation did not produce node.exe and npm.cmd." }
        $env:PATH = "$portableRoot;$env:PATH"
        Write-Host "Portable Node.js v$version is ready for Hermes." -ForegroundColor Green
        return $npm
    } finally {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}

function Ensure-DashboardWebBuild {
    param([string]$AgentRoot)
    if (-not $AgentRoot) { throw "Hermes source root could not be located; cannot prepare the Dashboard web UI." }
    $webDistIndex = Join-Path $AgentRoot "hermes_cli\web_dist\index.html"
    if (Test-Path -LiteralPath $webDistIndex) {
        Write-Host "[1/3] Hermes Dashboard web UI ........ ready" -ForegroundColor DarkGray
        return
    }

    Write-Host "[1/3] Hermes Dashboard web UI ........ missing" -ForegroundColor Yellow
    $npm = Find-Npm
    if (-not $npm) { $npm = Install-PortableNode }
    if (-not $npm) { throw "npm is unavailable after automatic dependency repair." }

    Write-Host "[2/3] Dashboard dependencies .......... preparing" -ForegroundColor Cyan
    $savedNodeEnv = $env:NODE_ENV
    try {
        Remove-Item Env:NODE_ENV -ErrorAction SilentlyContinue
        Push-Location $AgentRoot
        try {
            & $npm install --include=dev --workspace web
            if ($LASTEXITCODE -ne 0) { throw "npm install for the Hermes web workspace failed with exit code $LASTEXITCODE." }
            Write-Host "[2/3] Dashboard dependencies .......... ready" -ForegroundColor Green
            Write-Host "[3/3] Dashboard web build ............ building" -ForegroundColor Cyan
            & $npm run build -w web
            $buildExit = $LASTEXITCODE
            if ($buildExit -ne 0) {
                Write-Host "Initial Dashboard build failed; retrying once..." -ForegroundColor Yellow
                Start-Sleep -Seconds 2
                & $npm run build -w web
                $buildExit = $LASTEXITCODE
            }
            if ($buildExit -ne 0) { throw "Hermes Dashboard web build failed with exit code $buildExit." }
        } finally {
            Pop-Location
        }
    } finally {
        if ($null -eq $savedNodeEnv) { Remove-Item Env:NODE_ENV -ErrorAction SilentlyContinue } else { $env:NODE_ENV = $savedNodeEnv }
    }

    if (-not (Test-Path -LiteralPath $webDistIndex)) { throw "Hermes Dashboard build completed but hermes_cli\web_dist\index.html is still missing." }
    Write-Host "[3/3] Dashboard web build ............ ready" -ForegroundColor Green
}

function Get-PortOwnerPid {
    param([int]$Port)
    try {
        $connections = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop
        $pidValue = @($connections | Select-Object -ExpandProperty OwningProcess -Unique | Where-Object { $_ -gt 0 }) | Select-Object -First 1
        if ($pidValue) { return [int]$pidValue }
    } catch {}
    try {
        $line = netstat -ano -p tcp | Select-String -Pattern (":$Port\s+.*LISTENING\s+(\d+)\s*$") | Select-Object -First 1
        if ($line -and $line.Matches.Count -gt 0) { return [int]$line.Matches[0].Groups[1].Value }
    } catch {}
    return 0
}

function Get-ProcessInfoSafe {
    param([int]$ProcessId)
    try { return Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction Stop } catch { return $null }
}

function Test-IsHermesDashboardProcess {
    param([int]$ProcessId)
    if ($ProcessId -le 0) { return $false }
    $procInfo = Get-ProcessInfoSafe -ProcessId $ProcessId
    if (-not $procInfo) { return $false }
    $name = [string]$procInfo.Name
    $exe = [string]$procInfo.ExecutablePath
    $cmd = [string]$procInfo.CommandLine
    $combined = ($name + " " + $exe + " " + $cmd).ToLowerInvariant()
    $hermesHomeLower = $HermesHome.ToLowerInvariant()

    if ($combined.Contains("hermes.exe") -and $combined.Contains("dashboard")) { return $true }
    if ($combined.Contains("hermes-agent") -and $combined.Contains("dashboard")) { return $true }
    if ($combined.Contains($hermesHomeLower) -and $combined.Contains("dashboard") -and $combined.Contains("hermes")) { return $true }
    return $false
}

function Get-RunningHermesDashboardPids {
    $result = New-Object System.Collections.Generic.List[int]
    try {
        foreach ($procInfo in Get-CimInstance Win32_Process -ErrorAction Stop) {
            $pidValue = [int]$procInfo.ProcessId
            if ($pidValue -gt 0 -and (Test-IsHermesDashboardProcess -ProcessId $pidValue)) {
                if (-not $result.Contains($pidValue)) { $result.Add($pidValue) }
            }
        }
    } catch {}
    return @($result)
}

function Stop-HermesDashboardPid {
    param([int]$ProcessId)
    if ($ProcessId -le 0) { return }
    $procInfo = Get-ProcessInfoSafe -ProcessId $ProcessId
    if (-not $procInfo) { return }
    if (-not (Test-IsHermesDashboardProcess -ProcessId $ProcessId)) { return }
    Write-Host "Closing Hermes Dashboard process PID $ProcessId..." -ForegroundColor Yellow
    Stop-Process -Id $ProcessId -Force -ErrorAction Stop
}

function Wait-PortFree {
    param([int]$Port, [int]$Seconds = 10)
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        if (-not (Test-LocalPort -Port $Port)) { return $true }
        Start-Sleep -Milliseconds 250
    }
    return -not (Test-LocalPort -Port $Port)
}

function Find-FreePort {
    foreach ($candidate in 9120..9199) {
        if (-not (Test-LocalPort -Port $candidate)) { return $candidate }
    }
    return 0
}

function Show-RuntimeDiagnostics {
    param([int]$Port)
    Write-Host "" 
    Write-Host "Hermes runtime diagnostics" -ForegroundColor Yellow
    Write-Host "--------------------------" -ForegroundColor Yellow

    $installedManifest = Join-Path $HermesHome "plugins\hermes-extensions\dashboard\manifest.json"
    if (Test-Path -LiteralPath $installedManifest) {
        try {
            $manifest = Get-Content -LiteralPath $installedManifest -Raw -Encoding UTF8 | ConvertFrom-Json
            Write-Host ("Installed dashboard manifest api: " + [string]$manifest.api)
            Write-Host ("Installed dashboard manifest name: " + [string]$manifest.name)
            Write-Host ("Installed dashboard manifest version: " + [string]$manifest.version)
        } catch {
            Write-Host ("Could not parse installed dashboard manifest: " + $_.Exception.Message)
        }
    } else {
        Write-Host "Installed dashboard manifest is missing."
    }

    try {
        $pluginsUrl = "http://127.0.0.1:$Port/api/dashboard/plugins"
        $pluginsResponse = Invoke-WebRequest -Uri $pluginsUrl -UseBasicParsing -TimeoutSec 4
        Write-Host ("Dashboard plugin discovery HTTP: " + [int]$pluginsResponse.StatusCode)
        if ($pluginsResponse.Content) {
            $text = [string]$pluginsResponse.Content
            if ($text.Length -gt 4000) { $text = $text.Substring(0,4000) + "..." }
            Write-Host "Dashboard plugin discovery response:"
            Write-Host $text
        }
    } catch {
        Write-Host ("Dashboard plugin discovery request failed: " + $_.Exception.Message)
    }

    $errorsLog = Join-Path $HermesHome "logs\errors.log"
    if (Test-Path -LiteralPath $errorsLog) {
        Write-Host ""
        Write-Host "Relevant Hermes errors.log entries:" -ForegroundColor Yellow
        $all = @(Get-Content -LiteralPath $errorsLog -Tail 500 -ErrorAction SilentlyContinue)
        $diagnosticMatches = New-Object System.Collections.Generic.List[string]
        for ($i = 0; $i -lt $all.Count; $i++) {
            $lineText = [string]$all[$i]
            if ($lineText -match 'hermes-extensions|Failed to load plugin|plugin_api|dashboard plugin') {
                $start = [Math]::Max(0, $i - 3)
                $end = [Math]::Min($all.Count - 1, $i + 12)
                for ($j = $start; $j -le $end; $j++) {
                    $entry = [string]$all[$j]
                    if (-not $diagnosticMatches.Contains($entry)) { [void]$diagnosticMatches.Add($entry) }
                }
            }
        }
        if ($diagnosticMatches.Count -gt 0) {
            $diagnosticMatches | ForEach-Object { Write-Host $_ }
        } else {
            Write-Host "No hermes-extensions/plugin API error was found in the last 500 lines."
            Write-Host "Last 80 lines of errors.log:"
            $all | Select-Object -Last 80 | ForEach-Object { Write-Host $_ }
        }
    } else {
        Write-Host "Hermes errors.log does not exist at $errorsLog"
    }
    Write-Host "--------------------------" -ForegroundColor Yellow
}

$hermes = Find-Hermes
if (-not $hermes) { throw "Hermes is not installed or its launcher could not be found." }
$hermesAgentRoot = Find-HermesAgentRoot -HermesPath $hermes
Ensure-DashboardWebBuild -AgentRoot $hermesAgentRoot

$Port = $PreferredPort
$preferredInUse = Test-LocalPort -Port $PreferredPort
$preferredOwner = if ($preferredInUse) { Get-PortOwnerPid -Port $PreferredPort } else { 0 }
$preferredIsHermes = $preferredOwner -gt 0 -and (Test-IsHermesDashboardProcess -ProcessId $preferredOwner)

if ($preferredInUse -and (Test-ControlCenterApi -Port $PreferredPort)) {
    Write-Host "Hermes Dashboard is already running with Control Center API on port $PreferredPort." -ForegroundColor Green
    if (-not $NoOpen) { Start-Process "http://127.0.0.1:$PreferredPort/management-center" | Out-Null }
    exit 0
}

if ($preferredInUse -and $preferredIsHermes) {
    Write-Host "Port $PreferredPort is held by an old Hermes Dashboard. Restarting it..." -ForegroundColor Yellow
    try { & $hermes dashboard --stop 2>&1 | Out-Host } catch {}
    Start-Sleep -Milliseconds 500
    if (Test-LocalPort -Port $PreferredPort) {
        Stop-HermesDashboardPid -ProcessId $preferredOwner
    }
    if (-not (Wait-PortFree -Port $PreferredPort -Seconds 10)) {
        throw "Old Hermes Dashboard was stopped but port $PreferredPort did not release in time."
    }
}
elseif ($preferredInUse) {
    $runningHermes = @(Get-RunningHermesDashboardPids)
    if ($runningHermes.Count -gt 0) {
        Write-Host "Port $PreferredPort belongs to another application, but Hermes Dashboard process(es) also exist: $($runningHermes -join ', ')." -ForegroundColor Yellow
        foreach ($pidValue in $runningHermes) {
            try {
                Stop-HermesDashboardPid -ProcessId $pidValue
            } catch {
                Write-Host ("Could not close Hermes PID {0}: {1}" -f $pidValue, $_.Exception.Message) -ForegroundColor Yellow
            }
        }
        Start-Sleep -Milliseconds 500
    }

    $Port = Find-FreePort
    if ($Port -eq 0) { throw "Port $PreferredPort is used by another application and no free Dashboard port was found from 9120 through 9199." }
    $owner = Get-ProcessInfoSafe -ProcessId $preferredOwner
    $detail = if ($owner) { (([string]$owner.Name) + " " + ([string]$owner.CommandLine)).Trim() } else { "PID $preferredOwner" }
    Write-Host "Port $PreferredPort is occupied by a non-Hermes process: $detail" -ForegroundColor Yellow
    Write-Host "No usable Hermes Dashboard is running there. Starting Hermes Dashboard on port $Port instead." -ForegroundColor Yellow
}

$DashboardUrl = "http://127.0.0.1:$Port"
$StdoutLog = Join-Path $LogDir ("dashboard-$Port.out.log")
$StderrLog = Join-Path $LogDir ("dashboard-$Port.err.log")
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Remove-Item $StdoutLog,$StderrLog -Force -ErrorAction SilentlyContinue

Write-Host "Hermes executable: $hermes"
Write-Host "Starting fresh Hermes Dashboard on $DashboardUrl ..." -ForegroundColor Cyan
$proc = Start-Process -FilePath $hermes -ArgumentList @("dashboard","--skip-build","--no-open","--host",$HostName,"--port",[string]$Port) -PassThru -WindowStyle Hidden -RedirectStandardOutput $StdoutLog -RedirectStandardError $StderrLog
Write-Host ("Dashboard launcher PID: " + $proc.Id)
Write-Host "Waiting for Dashboard and Control Center API to become ready..."

$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
while ((Get-Date) -lt $deadline) {
    if ((Test-LocalPort -Port $Port) -and (Test-ControlCenterApi -Port $Port)) {
        Write-Host "Hermes Dashboard and Control Center API are ready on port $Port." -ForegroundColor Green
        if (-not $NoOpen) {
            Start-Process "$DashboardUrl/management-center" | Out-Null
            Write-Host "Opened $DashboardUrl/management-center" -ForegroundColor Green
        }
        exit 0
    }
    try { $proc.Refresh() } catch {}
    if ($proc.HasExited) {
        if (Test-Path $StdoutLog) { Get-Content $StdoutLog -Tail 160 | Out-Host }
        if (Test-Path $StderrLog) { Get-Content $StderrLog -Tail 160 | Out-Host }
        Show-RuntimeDiagnostics -Port $Port
        throw "Hermes Dashboard exited before Control Center API became ready."
    }
    Start-Sleep -Milliseconds 500
}

if (Test-Path $StdoutLog) { Get-Content $StdoutLog -Tail 160 | Out-Host }
if (Test-Path $StderrLog) { Get-Content $StderrLog -Tail 160 | Out-Host }
Show-RuntimeDiagnostics -Port $Port
try { if (-not $proc.HasExited) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue } } catch {}
throw "Hermes Dashboard started on $DashboardUrl but Control Center API did not become ready within $TimeoutSeconds seconds."
