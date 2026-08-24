param(
    [ValidateSet("Auto", "Install", "UpdateHermes", "UpdatePlugin", "Repair", "Dashboard")]
    [string]$Action = "Auto",
    [switch]$NoPrompt,
    [switch]$SkipHermesUpdate,
    [switch]$NoDashboard,
    [switch]$NoEnable
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$ProgressPreference = "SilentlyContinue"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$LocalInstaller = Join-Path $Root "install.ps1"
$LocalDoctor = Join-Path $Root "doctor.ps1"
$DashboardLauncher = Join-Path $Root "Dashboard-Launch-v3.ps1"
$HermesHome = if ($env:HERMES_HOME) { $env:HERMES_HOME } elseif ($env:LOCALAPPDATA -and (Test-Path (Join-Path $env:LOCALAPPDATA "hermes"))) { Join-Path $env:LOCALAPPDATA "hermes" } elseif ($env:LOCALAPPDATA) { Join-Path $env:LOCALAPPDATA "hermes" } else { Join-Path $HOME ".hermes" }
$env:HERMES_HOME = $HermesHome

$OfficialHermesInstaller = "https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.ps1"
$HermesVersionSource = "https://raw.githubusercontent.com/NousResearch/hermes-agent/main/pyproject.toml"
$ControlCenterVersionSource = "https://raw.githubusercontent.com/Neal86/Hermes-Control-Center/main/plugin.yaml"
$ControlCenterBranchApi = "https://api.github.com/repos/Neal86/Hermes-Control-Center/branches/main"

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host ("==> " + $Message) -ForegroundColor Cyan
}

function Get-RemoteText([string]$Uri) {
    try {
        $separator = if ($Uri.Contains("?")) { "&" } else { "?" }
        $freshUri = $Uri + $separator + "hcc_cb=" + [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
        return (Invoke-WebRequest -UseBasicParsing -Uri $freshUri -TimeoutSec 15 -Headers @{ "Cache-Control" = "no-cache, no-store, max-age=0"; "Pragma" = "no-cache"; "User-Agent" = "Hermes-Control-Center-Setup" }).Content
    }
    catch { return $null }
}

function Parse-Version([string]$Text) {
    if (-not $Text) { return $null }
    if ($Text -match '(?i)(?:^|[^0-9])v?([0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?)') { return $Matches[1] }
    return $null
}

function Version-Core([string]$Version) {
    if (-not $Version) { return $null }
    try { return [version](($Version -split '[-+]', 2)[0]) } catch { return $null }
}

function Compare-Version([string]$Left, [string]$Right) {
    $a = Version-Core $Left
    $b = Version-Core $Right
    if ($null -eq $a -or $null -eq $b) { return $null }
    return $a.CompareTo($b)
}

function Read-ManifestVersion([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    try {
        $text = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
        if ($text -match '(?m)^version:\s*["'']?([^\s"'']+)["'']?\s*$') { return $Matches[1].Trim() }
    } catch {}
    return $null
}

function Get-ControlCenterMainSha {
    try {
        $json = Get-RemoteText $ControlCenterBranchApi
        if (-not $json) { return $null }
        $branch = $json | ConvertFrom-Json
        $sha = [string]$branch.commit.sha
        if ($sha -match '^[0-9a-f]{40}$') { return $sha }
    } catch {}
    return $null
}

function Refresh-HermesPath {
    $candidates = @(
        (Join-Path $HermesHome "hermes-agent\bin"),
        (Join-Path $HermesHome "bin")
    )
    foreach ($dir in $candidates) {
        if ($dir -and (Test-Path -LiteralPath $dir) -and (($env:PATH -split ';') -notcontains $dir)) {
            $env:PATH = "$dir;$env:PATH"
        }
    }
    return Get-Command hermes -ErrorAction SilentlyContinue
}

function Get-HermesCommand {
    $cmd = Get-Command hermes -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd }
    return Refresh-HermesPath
}

function Get-HermesInstalledVersion {
    $cmd = Get-HermesCommand
    if (-not $cmd) { return $null }
    try { return Parse-Version ((& $cmd.Source --version 2>&1 | Out-String).Trim()) } catch { return $null }
}

function Get-HermesLatestVersion {
    $text = Get-RemoteText $HermesVersionSource
    if ($text -and $text -match '(?m)^version\s*=\s*["'']([^"'']+)["'']\s*$') { return $Matches[1].Trim() }
    return $null
}

function Test-HermesRuntimeNeedsUpdate {
    $cmd = Get-HermesCommand
    if (-not $cmd) { return $false }
    try {
        $versionText = (& $cmd.Source --version 2>&1 | Out-String)
        if ($versionText -match '(?i)update available') { return $true }
        $doctorText = (& $cmd.Source doctor 2>&1 | Out-String)
        return $doctorText -match '(?i)SQLite .*WAL-reset bug|run [`'']?hermes update'
    } catch { return $false }
}

function Get-ControlCenterInstalledVersion {
    return Read-ManifestVersion (Join-Path $HermesHome "plugins\hermes-extensions\plugin.yaml")
}

function Get-ControlCenterBundledVersion {
    return Read-ManifestVersion (Join-Path $Root "plugin.yaml")
}

function Get-ControlCenterLatestVersion {
    $sha = Get-ControlCenterMainSha
    $source = if ($sha) { "https://raw.githubusercontent.com/Neal86/Hermes-Control-Center/$sha/plugin.yaml" } else { $ControlCenterVersionSource }
    $text = Get-RemoteText $source
    if ($text -and $text -match '(?m)^version:\s*["'']?([^\s"'']+)["'']?\s*$') { return $Matches[1].Trim() }
    return Get-ControlCenterBundledVersion
}

function Run-OfficialHermesInstaller {
    Write-Step "Running official Hermes Windows installer"
    $temp = Join-Path $env:TEMP ("hermes-install-" + [Guid]::NewGuid().ToString("N") + ".ps1")
    try {
        Invoke-WebRequest -UseBasicParsing -Uri $OfficialHermesInstaller -OutFile $temp
        & powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File $temp -SkipSetup -HermesHome $HermesHome
        if ($LASTEXITCODE -ne 0) { throw "Official Hermes installer exited with code $LASTEXITCODE." }
        $officialLauncher = Join-Path $HermesHome "hermes-agent\bin\hermes.exe"
        if (-not (Test-Path -LiteralPath $officialLauncher)) {
            throw "Hermes installer completed, but the official launcher was not found at '$officialLauncher'."
        }
        $officialVersion = Parse-Version ((& $officialLauncher --version 2>&1 | Out-String).Trim())
        if (-not $officialVersion) { throw "Official Hermes launcher was installed but its version could not be verified." }
        $officialBin = Split-Path -Parent $officialLauncher
        $env:PATH = (($env:PATH -split ';' | Where-Object { $_ -and ($_ -ne $officialBin) }) -join ';')
        $env:PATH = "$officialBin;$env:PATH"
        Write-Host "Official Hermes Windows install is active (v$officialVersion)." -ForegroundColor Green
    } finally {
        Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue
    }
}

function Get-HermesInstallKind {
    $cmd = Get-HermesCommand
    if (-not $cmd) { return "missing" }
    $source = [string]$cmd.Source
    if ($source -match '(?i)[\\/]uv[\\/]tools[\\/]hermes-agent[\\/]') { return "uv-tool" }
    try {
        $text = & $cmd.Source --version 2>&1 | Out-String
        if ($text -match '(?m)^Project:\s*(.+?)\s*$') {
            $project = $Matches[1].Trim()
            if ($project -match '(?i)[\\/]uv[\\/]tools[\\/]hermes-agent[\\/]') { return "uv-tool" }
            if ($project -match '(?i)[\\/]hermes[\\/]hermes-agent[\\/]') { return "official-windows" }
        }
    } catch {}
    if ($source -match '(?i)[\\/]hermes[\\/]') { return "official-windows" }
    return "external"
}

function Get-RunningHermesDashboardProcesses {
    $hermesHomeLower = ([string]$HermesHome).ToLowerInvariant()
    $matches = @()
    try {
        foreach ($proc in Get-CimInstance Win32_Process -ErrorAction Stop) {
            $cmd = [string]$proc.CommandLine
            $exe = [string]$proc.ExecutablePath
            $combined = ($exe + " " + $cmd).ToLowerInvariant()
            if (-not $combined.Contains($hermesHomeLower) -or -not $combined.Contains("dashboard") -or -not $combined.Contains("hermes")) { continue }
            $matches += $proc
        }
    } catch {}
    return @($matches)
}

function Get-RunningHermesDashboardPort {
    foreach ($proc in @(Get-RunningHermesDashboardProcesses)) {
        $cmd = [string]$proc.CommandLine
        if ($cmd -match '(?i)--port\s+(\d+)') { return [int]$Matches[1] }
    }
    if (@(Get-RunningHermesDashboardProcesses).Count -gt 0) { return 9119 }
    return 0
}

function Wait-HermesDashboardStopped {
    param([int]$TimeoutSeconds = 15)
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        if (@(Get-RunningHermesDashboardProcesses).Count -eq 0) { return $true }
        Start-Sleep -Milliseconds 250
    } while ([DateTime]::UtcNow -lt $deadline)
    return $false
}

function Stop-HermesDashboardForUpdate {
    $running = @(Get-RunningHermesDashboardProcesses)
    if ($running.Count -eq 0) { return }
    try {
        & (Get-HermesCommand).Source dashboard --stop | Out-Host
    } catch {}
    Start-Sleep -Milliseconds 500
    $remaining = @(Get-RunningHermesDashboardProcesses)
    if ($remaining.Count -gt 0) {
        Write-Host ("  -> Dashboard CLI stop left " + $remaining.Count + " process(es); stopping the Dashboard backend directly") -ForegroundColor DarkGray
        foreach ($proc in ($remaining | Sort-Object ProcessId -Descending)) {
            Stop-Process -Id ([int]$proc.ProcessId) -Force -ErrorAction SilentlyContinue
        }
    }
    if (-not (Wait-HermesDashboardStopped)) { throw "Hermes Dashboard did not stop cleanly before runtime update." }
}

function Start-HermesDashboardAfterUpdate {
    param([int]$Port)
    if ($Port -le 0) { return }
    $cmd = Get-HermesCommand
    if (-not $cmd) { throw "Hermes update completed but the launcher is unavailable for Dashboard restart." }
    Write-Host ("  -> Restarting Hermes Dashboard on port " + $Port) -ForegroundColor DarkGray
    Start-Process -FilePath $cmd.Source -ArgumentList @("dashboard","--skip-build","--no-open","--host","127.0.0.1","--port",[string]$Port) -WindowStyle Hidden | Out-Null
}

function Get-RunningHermesGatewayProfilesForUpdate {
    $profiles = New-Object System.Collections.Generic.List[string]
    $candidates = New-Object System.Collections.Generic.List[string]
    $candidates.Add("default")
    $profilesRoot = Join-Path $HermesHome "profiles"
    if (Test-Path -LiteralPath $profilesRoot) {
        Get-ChildItem -LiteralPath $profilesRoot -Directory -ErrorAction SilentlyContinue | ForEach-Object { $candidates.Add($_.Name) }
    }
    foreach ($profile in $candidates) {
        try {
            $output = if ($profile -eq "default") { & (Get-HermesCommand).Source gateway status 2>&1 | Out-String } else { & (Get-HermesCommand).Source -p $profile gateway status 2>&1 | Out-String }
            if ($output -match '(?i)Gateway process running') { $profiles.Add($profile) }
        } catch {}
    }
    return @($profiles)
}

function Ensure-HermesGatewayProfilesAfterUpdate {
    param([string[]]$Profiles)
    foreach ($profile in @($Profiles)) {
        $running = $false
        try {
            $status = if ($profile -eq "default") { & (Get-HermesCommand).Source gateway status 2>&1 | Out-String } else { & (Get-HermesCommand).Source -p $profile gateway status 2>&1 | Out-String }
            $running = $status -match '(?i)Gateway process running'
        } catch {}
        if ($running) { continue }
        Write-Host ("  -> Restoring Hermes Gateway profile " + $profile + " after runtime update") -ForegroundColor DarkGray
        if ($profile -eq "default") { & (Get-HermesCommand).Source gateway start | Out-Host } else { & (Get-HermesCommand).Source -p $profile gateway start | Out-Host }
        if ($LASTEXITCODE -ne 0) { throw "Hermes Gateway profile '$profile' failed to restart after runtime update." }
        $deadline = [DateTime]::UtcNow.AddSeconds(15)
        do {
            Start-Sleep -Milliseconds 500
            try {
                $status = if ($profile -eq "default") { & (Get-HermesCommand).Source gateway status 2>&1 | Out-String } else { & (Get-HermesCommand).Source -p $profile gateway status 2>&1 | Out-String }
                if ($status -match '(?i)Gateway process running') { $running = $true; break }
            } catch {}
        } while ([DateTime]::UtcNow -lt $deadline)
        if (-not $running) { throw "Hermes Gateway profile '$profile' did not become healthy after runtime update." }
    }
}

function Get-HermesCuaRefreshSetting {
    try {
        $value = (& (Get-HermesCommand).Source config get updates.refresh_cua_driver 2>$null | Out-String).Trim().ToLowerInvariant()
        if ($value -in @("true","false")) { return $value }
    } catch {}
    return $null
}

function Set-HermesCuaRefreshSetting {
    param([string]$Value)
    if ($Value -notin @("true","false")) { return }
    & (Get-HermesCommand).Source config set updates.refresh_cua_driver $Value | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Could not set updates.refresh_cua_driver=$Value before Hermes runtime update." }
}
function Update-Hermes {
    $installed = Get-HermesInstalledVersion
    if (-not $installed) {
        Run-OfficialHermesInstaller
        return
    }
    $latest = Get-HermesLatestVersion
    if (-not $latest) {
        Write-Warning "Could not verify the latest Hermes version. Update skipped."
        return
    }
    $cmp = Compare-Version $installed $latest
    if ($null -eq $cmp) {
        Write-Warning "Could not compare Hermes versions. Update skipped."
        return
    }
    if ($cmp -eq 0) {
        if (-not (Test-HermesRuntimeNeedsUpdate)) {
            Write-Host "Hermes Agent is already current (v$installed)." -ForegroundColor Green
            return
        }
        Write-Host "Hermes version matches, but its embedded runtime or checkout needs repair." -ForegroundColor Yellow
    }
    if ($cmp -gt 0) {
        Write-Host "Installed Hermes v$installed is newer than available v$latest. Downgrade blocked." -ForegroundColor Yellow
        return
    }

    $kind = Get-HermesInstallKind
    Write-Step "Updating Hermes Agent v$installed -> v$latest"
    if ($kind -eq "official-windows") {
        $dashboardPort = Get-RunningHermesDashboardPort
        $dashboardWasRunning = $dashboardPort -gt 0
        $gatewayProfiles = @(Get-RunningHermesGatewayProfilesForUpdate)
        $cuaRefreshSetting = Get-HermesCuaRefreshSetting
        $cuaRefreshTemporarilyDisabled = $cuaRefreshSetting -eq "true"
        try {
            if ($dashboardWasRunning) {
                Write-Host ("  -> Stopping Hermes Dashboard before runtime update (port " + $dashboardPort + ")") -ForegroundColor DarkGray
                Stop-HermesDashboardForUpdate
            }
            if ($cuaRefreshTemporarilyDisabled) {
                Write-Host "  -> Deferring optional cua-driver refresh until after the core Hermes update" -ForegroundColor DarkGray
                Set-HermesCuaRefreshSetting -Value "false"
            }
            & (Get-HermesCommand).Source update
            $updateExitCode = $LASTEXITCODE
            if ($updateExitCode -ne 0) {
                $installedAfterUpdate = Get-HermesInstalledVersion
                $runtimeStillNeedsUpdate = Test-HermesRuntimeNeedsUpdate
                if ($installedAfterUpdate -eq $latest -and -not $runtimeStillNeedsUpdate) {
                    Write-Warning ("Hermes update returned code " + $updateExitCode + " after reaching v" + $installedAfterUpdate + "; verified runtime is current, continuing.")
                } else {
                    throw "Hermes runtime update exited with code $updateExitCode."
                }
            }
        } finally {
            if ($cuaRefreshTemporarilyDisabled) {
                try { Set-HermesCuaRefreshSetting -Value $cuaRefreshSetting } catch { Write-Warning $_.Exception.Message }
            }
            Ensure-HermesGatewayProfilesAfterUpdate -Profiles $gatewayProfiles
            if ($dashboardWasRunning) { Start-HermesDashboardAfterUpdate -Port $dashboardPort }
        }
        return
    }
    if ($kind -eq "uv-tool") {
        Write-Host "Legacy uv-tool Hermes installation detected. Migrating to the supported official Windows installer..." -ForegroundColor Yellow
        Run-OfficialHermesInstaller
        return
    }
    throw "Hermes is installed from an external source. Setup will not overwrite it automatically."
}

function Run-PluginInstaller([string]$InstallerPath) {
    if (-not (Test-Path -LiteralPath $InstallerPath)) { throw "Missing Control Center installer: $InstallerPath" }
    $args = @()
    if ($NoEnable) { $args += "-NoEnable" }
    & powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File $InstallerPath @args
    if ($LASTEXITCODE -ne 0) { throw "Control Center installer exited with code $LASTEXITCODE." }
}

function Install-LocalControlCenter { Run-PluginInstaller $LocalInstaller }

function Install-LatestControlCenter([string]$LatestVersion) {
    $bundled = Get-ControlCenterBundledVersion
    $cmp = Compare-Version $bundled $LatestVersion
    if (-not $LatestVersion -or ($null -ne $cmp -and $cmp -ge 0)) {
        Install-LocalControlCenter
        return
    }

    $mainSha = Get-ControlCenterMainSha
    if (-not $mainSha) { throw "Could not resolve the current GitHub main commit SHA. Refusing an unpinned update." }
    $controlCenterZip = "https://github.com/Neal86/Hermes-Control-Center/archive/$mainSha.zip"

    Write-Step ("Downloading Hermes Control Center v" + $LatestVersion + " from commit " + $mainSha.Substring(0, 12))
    $tempRoot = Join-Path $env:TEMP ("hermes-control-center-" + [Guid]::NewGuid().ToString("N"))
    $zip = Join-Path $tempRoot "control-center.zip"
    $extract = Join-Path $tempRoot "src"
    try {
        New-Item -ItemType Directory -Force -Path $tempRoot, $extract | Out-Null
        Invoke-WebRequest -UseBasicParsing -Uri $controlCenterZip -OutFile $zip -Headers @{ "Cache-Control" = "no-cache" }
        Expand-Archive -LiteralPath $zip -DestinationPath $extract -Force

        $manifest = Get-ChildItem -LiteralPath $extract -Filter "plugin.yaml" -File -Recurse | Select-Object -First 1
        if (-not $manifest) { throw "Downloaded Control Center package does not contain plugin.yaml." }
        $packageVersion = Read-ManifestVersion $manifest.FullName
        if (-not $packageVersion -or $packageVersion -ne $LatestVersion) {
            throw "Downloaded package version mismatch. Expected v$LatestVersion but commit $mainSha contains v$packageVersion. Update aborted."
        }

        $packageRoot = Split-Path -Parent $manifest.FullName
        foreach ($releaseArtifact in @("dashboard\dist\index.js", "dashboard\dist\build-manifest.json", "dashboard\verify_bundle.py")) {
            if (-not (Test-Path -LiteralPath (Join-Path $packageRoot $releaseArtifact))) {
                throw "Downloaded Control Center package is not release-ready: missing $releaseArtifact. Update aborted before installation."
            }
        }

        $installer = Join-Path $packageRoot "install.ps1"
        if (-not (Test-Path -LiteralPath $installer)) { throw "Downloaded Control Center package does not contain install.ps1." }
        Run-PluginInstaller $installer

        $installedAfter = Get-ControlCenterInstalledVersion
        if ($installedAfter -ne $LatestVersion) {
            throw "Control Center install verification failed. Expected v$LatestVersion but installed v$installedAfter."
        }
        Write-Host ("Verified Control Center v" + $installedAfter + " from commit " + $mainSha.Substring(0, 12) + ".") -ForegroundColor Green
    } finally {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}

function Update-ControlCenter([switch]$ForceRepair) {
    if (-not (Get-HermesCommand)) { throw "Hermes is not installed." }
    if ($ForceRepair) {
        if (Test-Path -LiteralPath $LocalDoctor) {
            Write-Step "Control Center preflight"
            & powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File $LocalDoctor -Preflight
            if ($LASTEXITCODE -ne 0) { Write-Warning "Preflight reported issues; repair will reinstall anyway." }
        }
        Install-LocalControlCenter
        return
    }

    $installed = Get-ControlCenterInstalledVersion
    $latest = Get-ControlCenterLatestVersion
    if ($installed -and $latest) {
        $cmp = Compare-Version $installed $latest
        if ($null -ne $cmp -and $cmp -eq 0) {
            Write-Host "Hermes Control Center is already current (v$installed)." -ForegroundColor Green
            return
        }
        if ($null -ne $cmp -and $cmp -gt 0) {
            Write-Host "Installed Control Center v$installed is newer than available v$latest. Downgrade blocked." -ForegroundColor Yellow
            return
        }
    }
    Install-LatestControlCenter $latest
}

function Open-Dashboard {
    if (-not (Get-HermesCommand)) { throw "Hermes is not installed." }
    if (-not (Test-Path -LiteralPath $DashboardLauncher)) { throw "Missing Dashboard launcher: $DashboardLauncher" }
    & powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File $DashboardLauncher
    if ($LASTEXITCODE -ne 0) { throw "Dashboard launcher exited with code $LASTEXITCODE." }
}

function Show-OneShotMenu {
    while ($true) {
        $hInstalled = Get-HermesInstalledVersion
        $hLatest = Get-HermesLatestVersion
        $cInstalled = Get-ControlCenterInstalledVersion
        $cLatest = Get-ControlCenterLatestVersion
        Write-Host ""
        Write-Host "Hermes Control Center Setup" -ForegroundColor Green
        Write-Host "Hermes home: $HermesHome"
        Write-Host ("Hermes:         " + $(if ($hInstalled) { "v$hInstalled" } else { "not installed" }) + $(if ($hLatest) { "  latest v$hLatest" } else { "  latest unknown" }))
        Write-Host ("Control Center: " + $(if ($cInstalled) { "v$cInstalled" } else { "not installed" }) + $(if ($cLatest) { "  latest v$cLatest" } else { "  latest unknown" }))
        Write-Host ""
        Write-Host "  1. Install / update everything"
        Write-Host "  2. Update Hermes only"
        Write-Host "  3. Install / update Control Center only"
        Write-Host "  4. Repair Control Center"
        Write-Host "  5. Open Hermes Dashboard"
        Write-Host "  6. Exit"
        $choice = (Read-Host "Choose").Trim()
        switch ($choice) {
            "1" { return "Install" }
            "2" { return "UpdateHermes" }
            "3" { return "UpdatePlugin" }
            "4" { return "Repair" }
            "5" { return "Dashboard" }
            "6" { return "Exit" }
            "0" { return "Exit" }
            default { Write-Warning "Invalid selection. Choose 1-6." }
        }
    }
}

if ($Action -eq "Auto") {
    if ($NoPrompt) { $Action = "Install" }
    else {
        $Action = Show-OneShotMenu
        if ($Action -eq "Exit") { exit 0 }
    }
}

switch ($Action) {
    "Install" {
        if (-not $SkipHermesUpdate) { Update-Hermes }
        elseif (-not (Get-HermesCommand)) { throw "Hermes is not installed and Hermes installation was skipped." }
        if (-not (Get-HermesCommand)) { throw "Hermes installation/update completed but hermes is still unavailable in this session." }
        Update-ControlCenter
        if (-not $NoDashboard -and -not $NoPrompt) {
            $open = (Read-Host "Open Hermes Dashboard now? [Y/n]").Trim().ToLowerInvariant()
            if (-not $open -or $open -in @("y", "yes")) { Open-Dashboard }
        }
    }
    "UpdateHermes" { Update-Hermes }
    "UpdatePlugin" { Update-ControlCenter }
    "Repair" { Update-ControlCenter -ForceRepair }
    "Dashboard" { Open-Dashboard }
}

Write-Host ""
Write-Host "Done." -ForegroundColor Green
Write-Host "Hermes data under '$HermesHome' was preserved."
exit 0
