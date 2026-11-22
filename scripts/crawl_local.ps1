# Crawl the sources that block datacenter IPs (Eventbrite, Global Game Jam) from this computer
# and write them to the same Neon database the website reads. See DECISIONS.md / README.md.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\crawl_local.ps1
#
# First run: asks for the DIRECT Neon URL (hidden) and saves it in .env.local (git-ignored).
# -Only eventbrite|globalgamejam: crawl just one of them.
# -Scheduled (used by the weekly Windows task): never prompts; output goes to data\crawl_local.log.
param([switch]$Scheduled, [string]$Only = '')
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$envFile = Join-Path $root '.env.local'
if ($Scheduled) {
    New-Item -ItemType Directory -Force (Join-Path $root 'data') | Out-Null
    if (-not (Test-Path $envFile)) {
        "$(Get-Date -Format s) No $envFile yet: run this script once by hand to save the Neon URL." |
            Out-File -Append -Encoding utf8 (Join-Path $root 'data\crawl_local.log')
        exit 1
    }
}

if (-not (Test-Path $envFile)) {
    Write-Host 'Paste the DIRECT Neon connection string (Connection pooling OFF). Input is hidden.' -ForegroundColor Cyan
    $secure = Read-Host -AsSecureString
    $url = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)).Trim().Trim("'").Trim('"')
    if ($url -notmatch '^postgres(ql)?://') { Write-Host 'That does not look like a Postgres URL. Nothing was saved.' -ForegroundColor Red; exit 1 }
    Set-Content -Path $envFile -Value "DATABASE_URL=$url" -Encoding utf8
    Write-Host "Saved to $envFile (git-ignored)." -ForegroundColor Green
}

$line = Get-Content $envFile | Where-Object { $_ -like 'DATABASE_URL=*' } | Select-Object -First 1
if (-not $line) { Write-Host "No DATABASE_URL in $envFile" -ForegroundColor Red; exit 1 }
$env:DATABASE_URL = $line.Substring('DATABASE_URL='.Length)
$env:PYTHONIOENCODING = 'utf-8'
$python = Join-Path $root '.venv\Scripts\python.exe'
$workerArgs = @('-m', 'hackfinder.worker', '--pass', 'local')
if ($Only) { $workerArgs += @('--only', $Only) }
try {
    if ($Scheduled) {
        $ErrorActionPreference = 'Continue'  # Windows PowerShell wraps native stderr lines as errors
        "=== $(Get-Date -Format s) local crawl ===" | Out-File -Append -Encoding utf8 (Join-Path $root 'data\crawl_local.log')
        & $python @workerArgs 2>&1 | ForEach-Object { "$_" } |
            Out-File -Append -Encoding utf8 (Join-Path $root 'data\crawl_local.log')
    } else {
        & $python @workerArgs
    }
    exit $LASTEXITCODE
} finally {
    Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
}
