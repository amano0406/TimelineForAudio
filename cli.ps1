[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$CliArgs
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = $PSScriptRoot
. (Join-Path $repoRoot "scripts\docker-runtime.ps1")

Initialize-TfaDocker -RepoRoot $repoRoot
Initialize-TfaLocalFiles -RepoRoot $repoRoot

$requiresConfiguredWorker = Test-TfaCliRequiresConfiguredWorker -CliArgs $CliArgs
if ($requiresConfiguredWorker) {
    Assert-TfaGpuAvailableIfRequested -RepoRoot $repoRoot
}

$includeGpuCompose = ((Get-TfaComputeMode -RepoRoot $repoRoot) -eq "gpu") -and (Test-TfaNvidiaGpuAvailable)
$composeArgs = Get-TfaComposeArgs -RepoRoot $repoRoot -IncludeGpu:$includeGpuCompose
$docker = Get-TfaDockerCommand
Invoke-TfaWithFileLock -RepoRoot $repoRoot -LockName "docker-compose.lock" -ScriptBlock {
    if ($requiresConfiguredWorker) {
        $upArgs = @("compose", "--progress", "quiet") + $composeArgs + @("up", "-d", "--remove-orphans")
        if (Test-TfaWorkerFlavorMismatch -RepoRoot $repoRoot -ComposeArgs $composeArgs) {
            $upArgs += "--force-recreate"
        }
        $upArgs += "worker"
        $startResult = Invoke-TfaHiddenProcess -FilePath $docker -Arguments $upArgs -WorkingDirectory $repoRoot -SuppressOutput
    }
    else {
        $startResult = Invoke-TfaHiddenProcess -FilePath $docker -Arguments (@("compose", "--progress", "quiet") + $composeArgs + @("up", "-d", "--no-recreate", "worker")) -WorkingDirectory $repoRoot -SuppressOutput
    }
    if ($startResult.ExitCode -ne 0) {
        throw "Failed to start TimelineForAudio worker."
    }
}

$cliResult = Invoke-TfaHiddenProcess -FilePath $docker -Arguments (@("compose") + $composeArgs + @("exec", "-T", "worker", "python", "-m", "timeline_for_audio_worker") + @($CliArgs)) -WorkingDirectory $repoRoot -WriteOutput
$exitCode = $cliResult.ExitCode
if ($exitCode -ne 0) {
    [Console]::Error.WriteLine("TimelineForAudio CLI failed while invoking the Docker worker. Exit code: $exitCode")
    [Console]::Error.WriteLine("Run the same command from C:\apps\TimelineForAudio with .\cli.ps1 to inspect Docker worker output and settings.")
}
exit $exitCode
