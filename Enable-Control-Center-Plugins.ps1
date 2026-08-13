param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$HermesHome = if ($env:HERMES_HOME) { $env:HERMES_HOME } elseif ($env:LOCALAPPDATA -and (Test-Path (Join-Path $env:LOCALAPPDATA "hermes"))) { Join-Path $env:LOCALAPPDATA "hermes" } else { Join-Path $HOME ".hermes" }
$env:HERMES_HOME = $HermesHome

function Find-HermesPython {
    $candidates = @(
        (Join-Path $HermesHome "hermes-agent\venv\Scripts\python.exe"),
        (Join-Path $HermesHome "hermes-agent\.venv\Scripts\python.exe"),
        (Join-Path $HermesHome "venv\Scripts\python.exe"),
        (Join-Path $HermesHome ".venv\Scripts\python.exe")
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    $hermes = Get-Command hermes -ErrorAction SilentlyContinue
    if ($hermes) {
        try {
            $text = (& $hermes.Source --version 2>&1 | Out-String)
            if ($text -match "(?m)^Project:\s*(.+?)\s*$") {
                $project = $Matches[1].Trim()
                foreach ($rel in @("venv\Scripts\python.exe", ".venv\Scripts\python.exe")) {
                    $candidate = Join-Path $project $rel
                    if (Test-Path -LiteralPath $candidate) { return $candidate }
                }
            }
        } catch {}
    }
    return $null
}

$python = Find-HermesPython
if (-not $python) { throw "Could not locate Hermes Python." }

$code = @'
from hermes_cli.config import load_config, save_config
cfg = load_config()
plugins = cfg.setdefault("plugins", {})
enabled = plugins.get("enabled")
if not isinstance(enabled, list):
    enabled = []
for name in ("hermes-extensions", "wechat-desktop"):
    if name not in enabled:
        enabled.append(name)
plugins["enabled"] = enabled
save_config(cfg)
print("Enabled plugins: " + ", ".join(enabled))
'@

Write-Host "Enabling Control Center plugins through Hermes config..." -ForegroundColor Cyan
& $python -c $code
if ($LASTEXITCODE -ne 0) { throw "Hermes config update failed with exit code $LASTEXITCODE." }
Write-Host "Control Center plugins enabled." -ForegroundColor Green
exit 0
