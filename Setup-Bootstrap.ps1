param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$ProgressPreference = "SilentlyContinue"

$Repo = "Neal86/Hermes-Control-Center"
$BranchApi = "https://api.github.com/repos/$Repo/branches/main"
$TempRoot = Join-Path $env:TEMP ("hermes-control-center-setup-" + [Guid]::NewGuid().ToString("N"))
$ZipPath = Join-Path $TempRoot "source.zip"
$ExtractPath = Join-Path $TempRoot "source"

function Get-MainSha {
    $headers = @{
        "Cache-Control" = "no-cache, no-store, max-age=0"
        "Pragma" = "no-cache"
        "User-Agent" = "Hermes-Control-Center-Setup-Bootstrap"
    }
    $uri = $BranchApi + "?hcc_cb=" + [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
    $branch = (Invoke-WebRequest -UseBasicParsing -Uri $uri -Headers $headers -TimeoutSec 12).Content | ConvertFrom-Json
    $sha = [string]$branch.commit.sha
    if ($sha -notmatch '^[0-9a-f]{40}$') { throw "GitHub main branch returned an invalid commit SHA." }
    return $sha
}

try {
    New-Item -ItemType Directory -Force -Path $TempRoot,$ExtractPath | Out-Null
    $sha = Get-MainSha
    $archive = "https://github.com/$Repo/archive/$sha.zip"
    Write-Host ("Loading latest Setup runtime from commit " + $sha.Substring(0,12) + "...") -ForegroundColor DarkGray
    Invoke-WebRequest -UseBasicParsing -Uri $archive -OutFile $ZipPath -Headers @{ "Cache-Control" = "no-cache"; "User-Agent" = "Hermes-Control-Center-Setup-Bootstrap" } -TimeoutSec 30
    Expand-Archive -LiteralPath $ZipPath -DestinationPath $ExtractPath -Force

    $runner = Get-ChildItem -LiteralPath $ExtractPath -Filter "Setup-Loop-v8.ps1" -File -Recurse | Select-Object -First 1
    if (-not $runner) {
        $runner = Get-ChildItem -LiteralPath $ExtractPath -Filter "Setup-Loop-v7.ps1" -File -Recurse | Select-Object -First 1
    }
    if (-not $runner) { throw "Downloaded package does not contain a Setup loop." }

    # Run the fetched script in this PowerShell process so this console has a
    # single Read-Host owner. Do not spawn a second interactive PowerShell.
    & $runner.FullName
    $code = if ($null -ne $LASTEXITCODE) { [int]$LASTEXITCODE } else { 0 }
    exit $code
}
catch {
    Write-Host ("Unable to load latest Setup runtime: " + $_.Exception.Message) -ForegroundColor Red
    Write-Host "Setup stopped rather than falling back to a stale interactive runner." -ForegroundColor Yellow
    exit 2
}
finally {
    Remove-Item -LiteralPath $TempRoot -Recurse -Force -ErrorAction SilentlyContinue
}
