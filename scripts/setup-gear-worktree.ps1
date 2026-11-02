# Orca setup hook: run from the new worktree, or pass -WorktreeRoot explicitly.
[CmdletBinding()]
param(
    [string]$WorktreeRoot = (Get-Location).Path,
    [string]$ConfigSource,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$targetRoot = (Resolve-Path -LiteralPath $WorktreeRoot).Path
if (-not (Test-Path -LiteralPath (Join-Path $targetRoot 'run-gear-desktop.bat') -PathType Leaf)) {
    throw 'Run this hook from an osrs_recommender worktree containing run-gear-desktop.bat.'
}

Push-Location -LiteralPath $targetRoot
try {
    # The common Git directory identifies the original checkout even in a child worktree.
    $commonGit = & git rev-parse --path-format=absolute --git-common-dir
    if ($LASTEXITCODE -ne 0) { throw 'Cannot locate the shared Git directory.' }
    if (-not $ConfigSource) {
        $ConfigSource = Join-Path (Split-Path -Parent $commonGit) 'config.gear-desktop.yaml'
    }
    $config = Join-Path $targetRoot 'config.gear-desktop.yaml'
    $python = Join-Path $targetRoot '.venv\Scripts\python.exe'
    $copyConfig = -not (Test-Path -LiteralPath $config -PathType Leaf)
    if ($copyConfig -and -not (Test-Path -LiteralPath $ConfigSource -PathType Leaf)) {
        throw 'Private desktop config is missing. Configure it in the original checkout or pass -ConfigSource.'
    }

    # Check prerequisites before creating files or installing dependencies.
    Get-Command py.exe, node.exe, npm.cmd -ErrorAction Stop | Out-Null
    & py.exe -3.12 -c 'import sys; assert sys.version_info >= (3, 12)'
    if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.12 with the Windows Python launcher.' }
    & node.exe -e 'if (Number(process.versions.node.split(/[.]/)[0]) < 22) process.exit(1)'
    if ($LASTEXITCODE -ne 0) { throw 'Install Node.js 22 or newer.' }

    Write-Host "[gear-setup] Worktree: $targetRoot"
    if ($DryRun) {
        Write-Host '[gear-setup] Would create/reuse a local .venv and install this checkout with dev dependencies.'
        if ($copyConfig) {
            Write-Host '[gear-setup] Would copy the private desktop config from the original checkout or -ConfigSource.'
        } else {
            Write-Host '[gear-setup] Existing desktop config would be preserved.'
        }
        Write-Host '[gear-setup] Would validate local settings. No files changed.'
        return
    }

    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        & py.exe -3.12 -m venv (Join-Path $targetRoot '.venv')
        if ($LASTEXITCODE -ne 0) { throw 'Creating the worktree virtual environment failed.' }
    }
    & $python -c 'import sys; assert sys.version_info >= (3, 12)'
    if ($LASTEXITCODE -ne 0) { throw 'The existing worktree .venv needs Python 3.12 or newer.' }
    & $python -m pip install -e '.[dev]'
    if ($LASTEXITCODE -ne 0) { throw 'Installing worktree Python dependencies failed.' }
    if ($copyConfig) {
        # No -Force: reruns must never overwrite a worktree's private settings.
        [System.IO.File]::Copy((Resolve-Path -LiteralPath $ConfigSource).Path, $config, $false)
    }

    $previousConfig = $env:TRACKER_CONFIG_FILE
    try {
        $env:TRACKER_CONFIG_FILE = $config
        # YAML parser errors can contain source excerpts, so keep all validation output private.
        & $python -c 'from tracker.gear_desktop import load_desktop_settings; load_desktop_settings()' *> $null
        if ($LASTEXITCODE -ne 0) { throw 'Desktop configuration validation failed; check private settings.' }
    } finally {
        $env:TRACKER_CONFIG_FILE = $previousConfig
    }
    Write-Host '[gear-setup] Ready: run .\run-gear-desktop.bat in this worktree.'
    Write-Host '[gear-setup] The launcher builds React and downloads missing icons. Pi/Tailscale must be available.'
    Write-Host '[gear-setup] Stop other Gear instances on the same address/port, or change this worktree config port.'
} finally {
    Pop-Location
}
