[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = $PSScriptRoot
. (Join-Path $repoRoot "scripts\docker-runtime.ps1")

Initialize-TfaDocker -RepoRoot $repoRoot
Initialize-TfaLocalFiles -RepoRoot $repoRoot
Assert-TfaGpuAvailableIfRequested -RepoRoot $repoRoot

$composeArgs = Get-TfaComposeArgs -RepoRoot $repoRoot -IncludeGpu
$docker = Get-TfaDockerCommand
$computeMode = Get-TfaComputeMode -RepoRoot $repoRoot
Write-Host "Compute mode: $computeMode"
if ($computeMode -eq "gpu") {
    Write-Host "Starting GPU worker image."
}

Write-Host "Starting the worker container..."
Invoke-TfaWithFileLock -RepoRoot $repoRoot -LockName "docker-compose.lock" -ScriptBlock {
    & $docker compose @composeArgs up -d --remove-orphans worker
    if (-not $?) {
        throw "docker compose failed."
    }
}

Write-Host ""
Write-Host "TimelineForAudio worker is running."
Write-Host ""
Write-Host "CLI examples:"
Write-Host "  .\cli.ps1 settings init"
Write-Host "  .\cli.ps1 settings status"
Write-Host "  .\cli.ps1 items refresh"
Write-Host "  .\cli.ps1 runs list"
Write-Host ""
Write-Host "Docker status:"
& $docker compose @composeArgs ps
exit (Get-TfaLastExitCode)
