# Crawl the sources that block datacenter IPs (Eventbrite, Global Game Jam) from this computer
# and write them to the same Neon database the website reads. See DECISIONS.md / README.md.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\crawl_local.ps1
#
# First run: asks for the DIRECT Neon URL (hidden) and saves it in .env.local (git-ignored).
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$envFile = Join-Path $root '.env.local'

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
try {
    & (Join-Path $root '.venv\Scripts\python.exe') -m hackfinder.worker --pass local
    exit $LASTEXITCODE
} finally {
    Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
}
