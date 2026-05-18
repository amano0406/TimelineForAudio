[CmdletBinding()]
param(
    [int]$Port = 0,
    [switch]$Foreground
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = $PSScriptRoot
. (Join-Path $repoRoot "scripts\docker-runtime.ps1")

$runtimeDir = Join-Path $repoRoot ".runtime"

New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null

Initialize-TfaDocker -RepoRoot $repoRoot
Initialize-TfaLocalFiles -RepoRoot $repoRoot
Assert-TfaGpuAvailableIfRequested -RepoRoot $repoRoot

$runtime = Initialize-TfaRuntimeSettings -RepoRoot $repoRoot
if ($Port -gt 0) {
    $runtime.ApiPort = $Port
}
$env:TIMELINE_FOR_AUDIO_API_PORT = [string]$runtime.ApiPort
$composeArgs = Get-TfaComposeArgs -RepoRoot $repoRoot -IncludeGpu
$docker = Get-TfaDockerCommand
$computeMode = Get-TfaComputeMode -RepoRoot $repoRoot
Write-Host "Compute mode: $computeMode"
if ($computeMode -eq "gpu") {
    Write-Host "Starting GPU worker image."
}

Write-Host "Starting the worker container..."
Invoke-TfaWithFileLock -RepoRoot $repoRoot -LockName "docker-compose.lock" -ScriptBlock {
    $upArgs = @("compose") + $composeArgs + @("up", "-d", "--build", "--remove-orphans")
    if (Test-TfaWorkerFlavorMismatch -RepoRoot $repoRoot -ComposeArgs $composeArgs) {
        Write-Host "Existing worker flavor does not match settings.json. Recreating worker..."
        $upArgs += "--force-recreate"
    }
    $upArgs += "worker"
    $startResult = Invoke-TfaHiddenProcess -FilePath $docker -Arguments $upArgs -WorkingDirectory $repoRoot -WriteOutput
    if ($startResult.ExitCode -ne 0) {
        throw "docker compose failed."
    }
}

if ($Foreground) {
    Write-Host "-Foreground is accepted for compatibility; the local API now runs inside the worker container."
}

Write-Host ""
Write-Host "TimelineForAudio worker is running."
Write-Host "API: http://127.0.0.1:$($runtime.ApiPort)/health"
Write-Host ""
Write-Host "API examples:"
Write-Host "  curl.exe http://127.0.0.1:$($runtime.ApiPort)/health"
Write-Host "  Invoke-RestMethod -Method Post -Uri http://127.0.0.1:$($runtime.ApiPort)/settings/status -Body '{}'"
Write-Host "  Invoke-RestMethod -Method Post -Uri http://127.0.0.1:$($runtime.ApiPort)/items/refresh -Body '{}'"
Write-Host ""
Write-Host "Docker status:"
$statusResult = Invoke-TfaHiddenProcess -FilePath $docker -Arguments (@("compose") + $composeArgs + @("ps")) -WorkingDirectory $repoRoot -WriteOutput
$statusExitCode = $statusResult.ExitCode
if ($statusExitCode -ne 0) {
    Write-Warning "TimelineForAudio worker started, but Docker status could not be displayed. Docker status exit code: $statusExitCode"
    exit 0
}
exit 0
