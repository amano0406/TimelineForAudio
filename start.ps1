[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = $PSScriptRoot
. (Join-Path $repoRoot "scripts\docker-runtime.ps1")

Initialize-TfaDocker -RepoRoot $repoRoot
Initialize-TfaLocalFiles -RepoRoot $repoRoot
Assert-TfaGpuAvailableIfRequested -RepoRoot $repoRoot

$runtime = Initialize-TfaRuntimeSettings -RepoRoot $repoRoot
$composeArgs = Get-TfaComposeArgs -RepoRoot $repoRoot -IncludeGpu
$docker = Get-TfaDockerCommand
$computeMode = Get-TfaComputeMode -RepoRoot $repoRoot
Write-Host "Compute mode: $computeMode"
if ($computeMode -eq "gpu") {
    Write-Host "Starting GPU worker image."
}

Write-Host "Starting the worker and health API containers..."
Invoke-TfaWithFileLock -RepoRoot $repoRoot -LockName "docker-compose.lock" -ScriptBlock {
    $upArgs = @("compose") + $composeArgs + @("up", "-d", "--remove-orphans")
    if (Test-TfaWorkerFlavorMismatch -RepoRoot $repoRoot -ComposeArgs $composeArgs) {
        Write-Host "Existing worker flavor does not match settings.json. Recreating worker..."
        $upArgs += "--force-recreate"
    }
    $upArgs += @("worker", "api")
    $startResult = Invoke-TfaHiddenProcess -FilePath $docker -Arguments $upArgs -WorkingDirectory $repoRoot -WriteOutput
    if ($startResult.ExitCode -ne 0) {
        throw "docker compose failed."
    }
}

Write-Host ""
Write-Host "TimelineForAudio worker is running."
Write-Host "Health API: http://127.0.0.1:$($runtime.ApiPort)/health"
Write-Host ""
Write-Host "CLI examples:"
Write-Host "  .\cli.ps1 settings init"
Write-Host "  .\cli.ps1 settings status"
Write-Host "  .\cli.ps1 items refresh"
Write-Host "  .\cli.ps1 runs list"
Write-Host ""
Write-Host "Docker status:"
$statusResult = Invoke-TfaHiddenProcess -FilePath $docker -Arguments (@("compose") + $composeArgs + @("ps")) -WorkingDirectory $repoRoot -WriteOutput
$statusExitCode = $statusResult.ExitCode
if ($statusExitCode -ne 0) {
    Write-Warning "TimelineForAudio worker started, but Docker status could not be displayed. Docker status exit code: $statusExitCode"
    exit 0
}
exit 0
