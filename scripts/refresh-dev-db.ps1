param(
    [ValidatePattern('^(?:[A-Za-z0-9_][A-Za-z0-9_.-]*@)?[A-Za-z0-9_][A-Za-z0-9_.-]*$')][string]$ProductionHost = 'pi',
    [switch]$DryRun,
    [switch]$SkipMigrations
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repo '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Development Python is missing: $python. Run make install first."
}
$arguments = @((Join-Path $PSScriptRoot 'refresh_dev_db.py'), '--production-host', $ProductionHost)
if ($DryRun) { $arguments += '--dry-run' }
if ($SkipMigrations) { $arguments += '--skip-migrations' }
& $python @arguments
if ($LASTEXITCODE -ne 0) { throw "Development database refresh failed (exit $LASTEXITCODE)." }
