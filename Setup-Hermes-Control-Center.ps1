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
$PluginInstaller = Join-Path $Root "install.ps1"
$Doctor = Join-Path $Root "doctor.ps1"
$HermesHome = if ($env:HERMES_HOME) { $env:HERMES_HOME } else { Join-Path $HOME ".hermes" }
$OfficialInstallerUrl = "https://hermes-agent.nousresearch.com/install.ps1"
$HermesVersionSource = "https://raw.githubusercontent.com/NousResearch/hermes-agent/main/pyproject.toml"
$ControlCenterVersionSource = "https://raw.githubusercontent.com/Neal86/Hermes-Control-Center/main/plugin.yaml"
$ControlCenterZip = "https://github.com/Neal86/Hermes-Control-Center/archive/refs/heads/main.zip"

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host ("==> " + $Message) -ForegroundColor Cyan
}

function Get-HermesCommand {
    return Get-Command hermes -ErrorAction SilentlyContinue
}

function Get-SemVerFromText {
    param([string]$Text)
    if (-not $Text) { return $null }
    if ($Text -match '(?i)(?:^|[^0-9])v?([0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?)') {
        return $Matches[1]
    }
    return $null
}

function Convert-SemVer {
    param([string]$Version)
    if (-not $Version) { return $null }
    $core = ($Version -split '[-+]', 2)[0]
    try { return [version]$core } catch { return $null }
}

function Compare-SemVer {
    param([string]$Left, [string]$Right)
    $a = Convert-SemVer $Left
    $b = Convert-SemVer $Right
    if ($null -eq $a -or $null -eq $b) { return $null }
    return $a.CompareTo($b)
}

function Get-HermesVersionText {
    $cmd = Get-HermesCommand
    if (-not $cmd) { return $null }
    try { return (& $cmd.Source --version 2>&1 | Out-String).Trim() } catch { return $null }
}

function Get-HermesInstalledVersion {
    return Get-SemVerFromText (Get-HermesVersionText)
}

function Get-RemoteText {
    param([string]$Uri)
    try {
        return (Invoke-WebRequest -UseBasicParsing -Uri $Uri -TimeoutSec 12).Content
    } catch {
        return $null
    }
}

function Get-HermesLatestVersion {
    $text = Get-RemoteText $HermesVersionSource
    if ($text -and $text -match '(?m)^version\s*=\s*["'']([^"'']+)["'']\s*$') { return $Matches[1].Trim() }
    return $null
}

function Get-BundledControlCenterVersion {
    $manifest = Join-Path $Root "plugin.yaml"
    if (-not (Test-Path -LiteralPath $manifest)) { return $null }
    try {
        $text = Get-Content -LiteralPath $manifest -Raw -Encoding UTF8
        if ($text -match '(?m)^version:\s*["'']?([^\s"'']+)["'']?\s*$') { return $Matches[1].Trim() }
    } catch {}
    return $null
}

function Get-InstalledControlCenterVersion {
    $manifest = Join-Path $HermesHome "plugins\hermes-extensions\plugin.yaml"
    if (-not (Test-Path -LiteralPath $manifest)) { return $null }
    try {
        $text = Get-Content -LiteralPath $manifest -Raw -Encoding UTF8
        if ($text -match '(?m)^version:\s*["'']?([^\s"'']+)["'']?\s*$') { return $Matches[1].Trim() }
    } catch {}
    return $null
}

function Get-ControlCenterLatestVersion {
    $text = Get-RemoteText $ControlCenterVersionSource
    if ($text -and $text -match '(?m)^version:\s*["'']?([^\s"'']+)["'']?\s*$') { return $Matches[1].Trim() }
    return Get-BundledControlCenterVersion
}

function Get-UpdateState {
    param([string]$Installed, [string]$Latest)
    if (-not $Installed) { return "missing" }
    if (-not $Latest) { return "unknown" }
    $cmp = Compare-SemVer $Installed $Latest
    if ($null -eq $cmp) { return "unknown" }
    if ($cmp -lt 0) { return "update" }
    if ($cmp -eq 0) { return "current" }
    return "newer"
}

function Get-HermesInstallKind {
    $cmd = Get-HermesCommand
    if (-not $cmd) { return "missing" }
    $source = [string]$cmd.Source
    if ($source -match "(?i)[\\/]uv[\\/]tools[\\/]hermes-agent[\\/]") { return "uv-tool" }
    try {
        $version = (& $cmd.Source --version 2>&1 | Out-String)
        if ($version -match "(?im)^Project:\s*(.+?)\s*$") {
            $project = $Matches[1].Trim()
            if ($project -match "(?i)[\\/]uv[\\/]tools[\\/]hermes-agent[\\/]") { return "uv-tool" }
            if ($project -match "(?i)[\\/]hermes[\\/]hermes-agent[\\/]|[\\/]hermes-agent[\\/]") { return "official-windows" }
        }
    } catch {}
    if ($source -match "(?i)[\\/]hermes[\\/]hermes-agent[\\/]") { return "official-windows" }
    return "external"
}

function Ensure-Uv {
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if ($uv) { return $uv.Source }
    Write-Step "Installing uv"
    $installer = Join-Path $env:TEMP ("uv-install-" + [Guid]::NewGuid().ToString("N") + ".ps1")
    try {
        Invoke-WebRequest -UseBasicParsing -Uri "https://astral.sh/uv/install.ps1" -OutFile $installer
        & powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File $installer
        if ($LASTEXITCODE -ne 0) { throw "uv installer exited with code $LASTEXITCODE" }
    } finally {
        Remove-Item -LiteralPath $installer -Force -ErrorAction SilentlyContinue
    }
    $candidateDirs = @(
        (Join-Path $HOME ".local\bin"),
        (Join-Path $env:USERPROFILE ".local\bin"),
        (Join-Path $env:APPDATA "uv\bin")
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
    foreach ($dir in $candidateDirs) {
        if (($env:PATH -split ';') -notcontains $dir) { $env:PATH = "$dir;$env:PATH" }
    }
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if (-not $uv) { throw "uv installed but is not available in this PowerShell session." }
    return $uv.Source
}

function Invoke-OfficialHermesInstaller {
    param([switch]$IncludeDesktop)
    Write-Step "Running official Hermes Windows installer"
    $path = Join-Path $env:TEMP ("hermes-install-" + [Guid]::NewGuid().ToString("N") + ".ps1")
    try {
        Invoke-WebRequest -UseBasicParsing -Uri $OfficialInstallerUrl -OutFile $path
        $args = @("-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $path, "-SkipSetup")
        if ($IncludeDesktop) { $args += "-IncludeDesktop" }
        & powershell.exe @args
        if ($LASTEXITCODE -ne 0) { throw "Official Hermes installer exited with code $LASTEXITCODE" }
    } finally {
        Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
    }
}

function Install-Hermes {
    Write-Step "Installing Hermes Agent"
    Invoke-OfficialHermesInstaller
    $cmd = Get-HermesCommand
    if (-not $cmd) {
        $possible = @(
            (Join-Path $env:LOCALAPPDATA "hermes\bin"),
            (Join-Path $env:LOCALAPPDATA "hermes\hermes-agent\.venv\Scripts"),
            (Join-Path $env:APPDATA "uv\tools\hermes-agent\Scripts")
        ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
        foreach ($dir in $possible) { if (($env:PATH -split ';') -notcontains $dir) { $env:PATH = "$dir;$env:PATH" } }
        $cmd = Get-HermesCommand
    }
    if (-not $cmd) { throw "Hermes installation completed but 'hermes' is not available. Open a new PowerShell and rerun Setup." }
    Write-Host (Get-HermesVersionText)
}

function Update-Hermes {
    $kind = Get-HermesInstallKind
    if ($kind -eq "missing") { Install-Hermes; return $true }

    $installed = Get-HermesInstalledVersion
    $latest = Get-HermesLatestVersion
    $state = Get-UpdateState $installed $latest
    if ($state -eq "current") {
        Write-Host "Hermes Agent is already up to date (v$installed). Update skipped." -ForegroundColor Green
        return $false
    }
    if ($state -eq "newer") {
        Write-Host "Installed Hermes Agent v$installed is newer than available v$latest. Downgrade blocked." -ForegroundColor Yellow
        return $false
    }
    if ($state -eq "unknown") {
        Write-Warning "Could not verify the latest Hermes version. Hermes update is skipped to avoid an unnecessary or unsafe overwrite."
        return $false
    }

    Write-Step "Updating Hermes Agent v$installed -> v$latest ($kind)"
    if ($kind -eq "uv-tool") {
        $uv = Ensure-Uv
        & $uv tool upgrade hermes-agent
        if ($LASTEXITCODE -ne 0) { throw "uv tool upgrade hermes-agent failed with exit code $LASTEXITCODE" }
    } elseif ($kind -eq "official-windows") {
        Invoke-OfficialHermesInstaller
    } else {
        throw "Hermes is installed from an external/unknown source. Setup will not overwrite it automatically. Update that Hermes installation with its original package manager, then rerun Setup."
    }
    Write-Host (Get-HermesVersionText)
    return $true
}

function Invoke-PluginInstallerPath {
    param([string]$InstallerPath)
    if (-not (Test-Path -LiteralPath $InstallerPath)) { throw "Missing plugin installer: $InstallerPath" }
    $args = @()
    if ($NoEnable) { $args += "-NoEnable" }
    & $InstallerPath @args
    if ($LASTEXITCODE -ne 0) { throw "Control Center installer exited with code $LASTEXITCODE" }
}

function Invoke-LatestControlCenterInstaller {
    param([string]$LatestVersion)
    $bundled = Get-BundledControlCenterVersion
    $cmp = Compare-SemVer $bundled $LatestVersion
    if ($bundled -and $LatestVersion -and $null -ne $cmp -and $cmp -ge 0) {
        Invoke-PluginInstallerPath $PluginInstaller
        return
    }

    Write-Step "Downloading Hermes Control Center v$LatestVersion"
    $tempRoot = Join-Path $env:TEMP ("hermes-control-center-" + [Guid]::NewGuid().ToString("N"))
    $zip = Join-Path $tempRoot "control-center.zip"
    $extract = Join-Path $tempRoot "src"
    try {
        New-Item -ItemType Directory -Force -Path $tempRoot, $extract | Out-Null
        Invoke-WebRequest -UseBasicParsing -Uri $ControlCenterZip -OutFile $zip
        Expand-Archive -LiteralPath $zip -DestinationPath $extract -Force
        $installer = Get-ChildItem -LiteralPath $extract -Filter "install.ps1" -File -Recurse | Select-Object -First 1
        if (-not $installer) { throw "Downloaded Control Center package does not contain install.ps1" }
        Invoke-PluginInstallerPath $installer.FullName
    } finally {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}

function Invoke-PluginInstall {
    $installed = Get-InstalledControlCenterVersion
    $latest = Get-ControlCenterLatestVersion
    $state = Get-UpdateState $installed $latest

    if ($state -eq "current") {
        Write-Host "Hermes Control Center is already up to date (v$installed). Update skipped." -ForegroundColor Green
        return $false
    }
    if ($state -eq "newer") {
        Write-Host "Installed Hermes Control Center v$installed is newer than available v$latest. Downgrade blocked." -ForegroundColor Yellow
        return $false
    }
    if ($state -eq "unknown" -and $installed) {
        Write-Warning "Could not verify the latest Control Center version. Update is skipped to avoid an unnecessary or unsafe overwrite."
        return $false
    }

    Write-Step $(if ($installed) { "Updating Hermes Control Center v$installed -> v$latest" } else { "Installing Hermes Control Center v$latest" })
    Invoke-LatestControlCenterInstaller $latest
    return $true
}

function Invoke-Repair {
    if (-not (Get-HermesCommand)) { Install-Hermes }
    Write-Step "Repairing Control Center installation"
    if (Test-Path -LiteralPath $Doctor) {
        & $Doctor -Preflight
        if ($LASTEXITCODE -ne 0) { Write-Warning "Preflight reported issues; reinstalling plugin anyway." }
    }
    Invoke-PluginInstallerPath $PluginInstaller
}

function Open-HermesDashboard {
    $cmd = Get-HermesCommand
    if (-not $cmd) { throw "Hermes is not installed." }
    Write-Step "Starting Hermes Dashboard"
    Start-Process -FilePath $cmd.Source -ArgumentList @("dashboard") | Out-Null
    Write-Host "Hermes Dashboard launch requested."
}

function Confirm-Choice([string]$Prompt, [bool]$DefaultYes = $true) {
    if ($NoPrompt) { return $DefaultYes }
    $suffix = if ($DefaultYes) { "[Y/n]" } else { "[y/N]" }
    $answer = Read-Host "$Prompt $suffix"
    if ([string]::IsNullOrWhiteSpace($answer)) { return $DefaultYes }
    return $answer.Trim().ToLowerInvariant() -in @("y", "yes")
}

function Show-Menu {
    Write-Host ""
    Write-Host "Hermes Control Center Setup" -ForegroundColor Green
    Write-Host "Hermes home: $HermesHome"

    $hermesInstalled = Get-HermesInstalledVersion
    $hermesLatest = Get-HermesLatestVersion
    $hermesState = Get-UpdateState $hermesInstalled $hermesLatest
    $ccInstalled = Get-InstalledControlCenterVersion
    $ccLatest = Get-ControlCenterLatestVersion
    $ccState = Get-UpdateState $ccInstalled $ccLatest

    Write-Host ("Hermes:         " + $(if ($hermesInstalled) { "v$hermesInstalled" } else { "not installed" }) + $(if ($hermesLatest) { "  latest v$hermesLatest" } else { "  latest unknown" }))
    Write-Host ("Control Center: " + $(if ($ccInstalled) { "v$ccInstalled" } else { "not installed" }) + $(if ($ccLatest) { "  latest v$ccLatest" } else { "  latest unknown" }))
    Write-Host ""
    Write-Host "  1. Install / update everything"
    Write-Host ("  2. Update Hermes only" + $(if ($hermesState -in @("current", "newer")) { "  [already current]" } else { "" }))
    Write-Host ("  3. Install / update Control Center only" + $(if ($ccState -in @("current", "newer")) { "  [already current]" } else { "" }))
    Write-Host "  4. Repair Control Center"
    Write-Host "  5. Open Hermes Dashboard"
    Write-Host "  0. Exit"
    return (Read-Host "Choose").Trim()
}

if ($Action -eq "Auto" -and -not $NoPrompt) {
    $choice = Show-Menu
    $Action = switch ($choice) {
        "1" { "Install" }
        "2" { "UpdateHermes" }
        "3" { "UpdatePlugin" }
        "4" { "Repair" }
        "5" { "Dashboard" }
        "0" { return }
        default { throw "Unknown selection: $choice" }
    }
} elseif ($Action -eq "Auto") {
    $Action = "Install"
}

switch ($Action) {
    "Install" {
        if (-not (Get-HermesCommand)) {
            Install-Hermes
        } elseif (-not $SkipHermesUpdate) {
            Update-Hermes | Out-Null
        } else {
            Write-Host "Hermes update skipped by option."
        }
        Invoke-PluginInstall | Out-Null
        if (-not $NoDashboard -and (Confirm-Choice "Open Hermes Dashboard now?" $true)) { Open-HermesDashboard }
    }
    "UpdateHermes" { Update-Hermes | Out-Null }
    "UpdatePlugin" {
        if (-not (Get-HermesCommand)) { throw "Hermes is not installed. Use Action=Install first." }
        Invoke-PluginInstall | Out-Null
    }
    "Repair" { Invoke-Repair }
    "Dashboard" { Open-HermesDashboard }
}

Write-Host ""
Write-Host "Done." -ForegroundColor Green
Write-Host "Hermes data under '$HermesHome' was preserved; Setup does not delete Profiles, Skills, Cron, plugin-data, Provider settings, or resource bindings."
