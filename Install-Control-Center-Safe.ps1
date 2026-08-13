param(
    [switch]$Repair
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$ProgressPreference = "SilentlyContinue"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$InnerInstaller = Join-Path $Root "install.ps1"
$Requirements = Join-Path $Root "requirements-windows.txt"
$HermesHome = if ($env:HERMES_HOME) { $env:HERMES_HOME } elseif ($env:LOCALAPPDATA -and (Test-Path (Join-Path $env:LOCALAPPDATA "hermes"))) { Join-Path $env:LOCALAPPDATA "hermes" } else { Join-Path $HOME ".hermes" }
$env:HERMES_HOME = $HermesHome
$LogDir = Join-Path $HermesHome "logs\control-center"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Show-Tail([string]$Path, [int]$Lines = 120) {
    if (Test-Path -LiteralPath $Path) {
        Get-Content -LiteralPath $Path -Tail $Lines -ErrorAction SilentlyContinue | ForEach-Object { Write-Host ([string]$_) }
    }
}

function Run-Native {
    param(
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$Label,
        [string]$LogPrefix,
        [string]$WorkingDirectory = ""
    )
    $out = Join-Path $LogDir ($LogPrefix + ".out.log")
    $err = Join-Path $LogDir ($LogPrefix + ".err.log")
    Remove-Item $out,$err -Force -ErrorAction SilentlyContinue
    Write-Host ("  -> " + $Label) -ForegroundColor Cyan
    $params = @{
        FilePath = $FilePath
        ArgumentList = $Arguments
        Wait = $true
        PassThru = $true
        NoNewWindow = $true
        RedirectStandardOutput = $out
        RedirectStandardError = $err
    }
    if ($WorkingDirectory) { $params.WorkingDirectory = $WorkingDirectory }
    $proc = Start-Process @params
    Show-Tail $out
    Show-Tail $err
    return [int]$proc.ExitCode
}

function Find-HermesPython {
    foreach ($path in @(
        (Join-Path $HermesHome "hermes-agent\venv\Scripts\python.exe"),
        (Join-Path $HermesHome "hermes-agent\.venv\Scripts\python.exe"),
        (Join-Path $HermesHome "venv\Scripts\python.exe"),
        (Join-Path $HermesHome ".venv\Scripts\python.exe")
    )) {
        if (Test-Path -LiteralPath $path) { return $path }
    }
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if ($uv) {
        try {
            $toolDir = (& $uv.Source tool dir 2>$null | Select-Object -First 1).Trim()
            $candidate = Join-Path $toolDir "hermes-agent\Scripts\python.exe"
            if (Test-Path -LiteralPath $candidate) { return $candidate }
        } catch {}
    }
    return $null
}

if (-not (Get-Command hermes -ErrorAction SilentlyContinue)) { throw "Hermes is not installed or is not on PATH." }
if (-not (Test-Path -LiteralPath $InnerInstaller)) { throw "Missing install.ps1" }
if (-not (Test-Path -LiteralPath $Requirements)) { throw "Missing requirements-windows.txt" }

$python = Find-HermesPython
if (-not $python) { throw "Could not locate Hermes Python." }
Write-Host "Hermes home: $HermesHome"
Write-Host "Hermes Python: $python"
Write-Host "Installing Control Center dependencies safely..."

$depsOk = $false
$uv = Get-Command uv -ErrorAction SilentlyContinue
if ($uv) {
    $code = Run-Native -FilePath $uv.Source -Arguments @("pip","install","--python",$python,"-r",$Requirements) -Label "Installing dependencies with uv" -LogPrefix "deps-uv"
    if ($code -eq 0) { $depsOk = $true }
}
if (-not $depsOk) {
    $code = Run-Native -FilePath $python -Arguments @("-m","pip","install","-r",$Requirements) -Label "Installing dependencies with pip" -LogPrefix "deps-pip"
    if ($code -eq 0) { $depsOk = $true }
}
if (-not $depsOk) { throw "Unable to install Control Center dependencies. See logs under $LogDir." }

Write-Host "Installing Hermes Control Center..."
$installerArgs = @("-NoLogo","-NoProfile","-ExecutionPolicy","Bypass","-File",$InnerInstaller,"-SkipDependencies")
$code = Run-Native -FilePath "powershell.exe" -Arguments $installerArgs -Label "Installing plugin files and configuration" -LogPrefix "plugin-install" -WorkingDirectory $Root
if ($code -ne 0) { throw "Control Center installer failed with exit code $code. See logs under $LogDir." }

Write-Host "Hermes Control Center installation completed successfully." -ForegroundColor Green
exit 0
