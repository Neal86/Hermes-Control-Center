param(
    [Parameter(Mandatory=$true)][string]$StopFile
)

$ErrorActionPreference = "SilentlyContinue"
$ProgressPreference = "SilentlyContinue"
$HermesHome = if ($env:HERMES_HOME) { $env:HERMES_HOME } elseif ($env:LOCALAPPDATA) { Join-Path $env:LOCALAPPDATA "hermes" } else { Join-Path $HOME ".hermes" }
$ControlLogDir = Join-Path $HermesHome "logs\control-center"
$HermesErrors = Join-Path $HermesHome "logs\errors.log"
$positions = @{}

function Get-TrackedFiles {
    $files = @()
    if (Test-Path -LiteralPath $ControlLogDir) {
        $files += @(Get-ChildItem -LiteralPath $ControlLogDir -File -Filter "*.log" -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName)
    }
    if (Test-Path -LiteralPath $HermesErrors) { $files += $HermesErrors }
    return @($files | Select-Object -Unique)
}

foreach ($file in Get-TrackedFiles) {
    try { $positions[$file] = @(Get-Content -LiteralPath $file -ErrorAction SilentlyContinue).Count } catch { $positions[$file] = 0 }
}

while (-not (Test-Path -LiteralPath $StopFile)) {
    foreach ($file in Get-TrackedFiles) {
        try {
            $lines = @(Get-Content -LiteralPath $file -ErrorAction SilentlyContinue)
            $count = $lines.Count
            if (-not $positions.ContainsKey($file)) { $positions[$file] = 0 }
            $start = [int]$positions[$file]
            if ($count -lt $start) { $start = 0 }
            if ($count -gt $start) {
                $name = Split-Path -Leaf $file
                Write-Host ("`n[Live log: " + $name + "]") -ForegroundColor DarkGray
                for ($i = $start; $i -lt $count; $i++) { Write-Host ([string]$lines[$i]) }
                $positions[$file] = $count
            }
        } catch {}
    }
    Start-Sleep -Milliseconds 250
}
