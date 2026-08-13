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

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host ("==> " + $Message) -ForegroundColor Cyan
}

function Get-HermesCommand {
    return Get-Command hermes -ErrorAction SilentlyContinue
}

function Get-HermesVersion {
    $cmd = Get-HermesCommand
    if (-not $cmd) { return $null }
    try {
        $text = (& $cmd.Source --version 2>&1 | Out-String).Trim()
        return $text
    } catch { return $null }
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
    Write-Host (Get-HermesVersion)
}

function Update-Hermes {
    $kind = Get-HermesInstallKind
    if ($kind -eq "missing") { Install-Hermes; return }
    Write-Step "Updating Hermes Agent ($kind)"
    if ($kind -eq "uv-tool") {
        $uv = Ensure-Uv
        & $uv tool upgrade hermes-agent
        if ($LASTEXITCODE -ne 0) { throw "uv tool upgrade hermes-agent failed with exit code $LASTEXITCODE" }
    } elseif ($kind -eq "official-windows") {
        Invoke-OfficialHermesInstaller
    } else {
        throw "Hermes is installed from an external/unknown source. Setup will not overwrite it automatically. Update that Hermes installation with its original package manager, then rerun Setup."
    }
    Write-Host (Get-HermesVersion)
}

function Invoke-PluginInstall {
    if (-not (Test-Path -LiteralPath $PluginInstaller)) { throw "Missing plugin installer: $PluginInstaller" }
    Write-Step "Installing / updating Hermes Control Center"
    $args = @()
    if ($NoEnable) { $args += "-NoEnable" }
    & $PluginInstaller @args
    if ($LASTEXITCODE -ne 0) { throw "Control Center installer exited with code $LASTEXITCODE" }
}

function Invoke-Repair {
    if (-not (Get-HermesCommand)) { Install-Hermes }
    Write-Step "Repairing Control Center installation"
    if (Test-Path -LiteralPath $Doctor) {
        & $Doctor -Preflight
        if ($LASTEXITCODE -ne 0) { Write-Warning "Preflight reported issues; reinstalling plugin anyway." }
    }
    Invoke-PluginInstall
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
    $version = Get-HermesVersion
    Write-Host ("Hermes: " + $(if ($version) { $version.Split([Environment]::NewLine)[0] } else { "not installed" }))
    Write-Host ""
    Write-Host "  1. Install / update everything"
    Write-Host "  2. Update Hermes only"
    Write-Host "  3. Install / update Control Center only"
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
        } elseif (-not $SkipHermesUpdate -and (Confirm-Choice "Hermes is already installed. Update Hermes before updating Control Center?" $false)) {
            Update-Hermes
        } else {
            Write-Host "Keeping current Hermes version."
            Write-Host (Get-HermesVersion)
        }
        Invoke-PluginInstall
        if (-not $NoDashboard -and (Confirm-Choice "Open Hermes Dashboard now?" $true)) { Open-HermesDashboard }
    }
    "UpdateHermes" { Update-Hermes }
    "UpdatePlugin" {
        if (-not (Get-HermesCommand)) { throw "Hermes is not installed. Use Action=Install first." }
        Invoke-PluginInstall
    }
    "Repair" { Invoke-Repair }
    "Dashboard" { Open-HermesDashboard }
}

Write-Host ""
Write-Host "Done." -ForegroundColor Green
Write-Host "Hermes data under '$HermesHome' was preserved; Setup does not delete Profiles, Skills, Cron, plugin-data, Provider settings, or resource bindings."
