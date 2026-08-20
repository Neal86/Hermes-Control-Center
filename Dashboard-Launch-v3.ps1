param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$ProgressPreference = "SilentlyContinue"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Inner = Join-Path $Root "Dashboard-Launch-v4.ps1"
$Probe = Join-Path $Root "Dashboard-Api-Probe.ps1"
$HermesHome = if ($env:HERMES_HOME) { $env:HERMES_HOME } elseif ($env:LOCALAPPDATA -and (Test-Path (Join-Path $env:LOCALAPPDATA "hermes"))) { Join-Path $env:LOCALAPPDATA "hermes" } else { Join-Path $HOME ".hermes" }
$env:HERMES_HOME = $HermesHome
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

if (-not (Test-Path -LiteralPath $Inner -PathType Leaf)) { throw "Missing Dashboard-Launch-v4.ps1" }

$LogDir = Join-Path $HermesHome "logs\control-center"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$DetachedScript = Join-Path $LogDir "dashboard-detached-launch.ps1"
$DetachedLog = Join-Path $LogDir "dashboard-detached-launch.log"
Remove-Item -LiteralPath $DetachedLog -Force -ErrorAction SilentlyContinue

function Escape-SingleQuoted([string]$Value) {
    return $Value.Replace("'", "''")
}

$homeEscaped = Escape-SingleQuoted $HermesHome
$innerEscaped = Escape-SingleQuoted $Inner
$logEscaped = Escape-SingleQuoted $DetachedLog
$launcher = @"
`$ErrorActionPreference = 'Stop'
`$env:HERMES_HOME = '$homeEscaped'
`$env:PYTHONUTF8 = '1'
`$env:PYTHONIOENCODING = 'utf-8'
try {
    & '$innerEscaped' *>&1 | Out-File -LiteralPath '$logEscaped' -Encoding utf8
    exit [int]`$LASTEXITCODE
} catch {
    (`$_ | Out-String) | Out-File -LiteralPath '$logEscaped' -Encoding utf8 -Append
    exit 1
}
"@
[System.IO.File]::WriteAllText($DetachedScript, $launcher, [System.Text.UTF8Encoding]::new($false))

Write-Host "Hermes home: $HermesHome"
Write-Host "Starting Dashboard launcher outside the Setup process tree..." -ForegroundColor Cyan

# Start through Win32_Process so the persistent Hermes Dashboard is not a child
# of the Setup's Start-Process -Wait job. PowerShell's Start-Process -Wait waits
# for descendants too, which was why option 5 never returned to the main menu.
$commandLine = 'powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "' + $DetachedScript.Replace('"','\"') + '"'
try {
    $created = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{ CommandLine = $commandLine }
} catch {
    throw "Unable to create detached Dashboard launcher: $($_.Exception.Message)"
}
if ([int]$created.ReturnValue -ne 0 -or [int]$created.ProcessId -le 0) {
    throw "Unable to create detached Dashboard launcher. Win32_Process.Create returned $($created.ReturnValue)."
}
$launcherPid = [int]$created.ProcessId
Write-Host "Detached Dashboard launcher PID: $launcherPid"

$deadline = (Get-Date).AddSeconds(45)
$finished = $false
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 250
    try {
        $null = Get-Process -Id $launcherPid -ErrorAction Stop
    } catch {
        $finished = $true
        break
    }
}
if (-not $finished) {
    Write-Host "Dashboard launcher is still running after 45 seconds; returning control to Setup anyway." -ForegroundColor Yellow
    exit 0
}

$text = ""
if (Test-Path -LiteralPath $DetachedLog) {
    try { $text = Get-Content -LiteralPath $DetachedLog -Raw -Encoding UTF8 } catch {}
    if ($text) { $text.TrimEnd() | Write-Host }
}

if ($text -match '(?m)Hermes Dashboard and Control Center API are ready on port \d+\.' -or
    $text -match '(?m)Hermes Dashboard is already running with Control Center API on port \d+\.' -or
    $text -match '(?m)Opened http://127\.0\.0\.1:\d+/management-center') {
    exit 0
}

if (Test-Path -LiteralPath $Probe) {
    try {
        & $Probe -Port 9119
        if ($LASTEXITCODE -eq 0) { exit 0 }
    } catch {
        Write-Host ("Exact API probe failed: " + $_.Exception.Message) -ForegroundColor Yellow
    }
}

if (-not $text) {
    Write-Host "Detached Dashboard launcher exited without a readable launch log." -ForegroundColor Red
}
exit 1
