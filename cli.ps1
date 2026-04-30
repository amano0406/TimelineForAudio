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

$composeArgs = Get-TfaComposeArgs -RepoRoot $repoRoot -IncludeGpu:$requiresConfiguredWorker
$docker = Get-TfaDockerCommand
Invoke-TfaWithFileLock -RepoRoot $repoRoot -LockName "docker-compose.lock" -ScriptBlock {
    if ($requiresConfiguredWorker) {
        & $docker compose --progress quiet @composeArgs up -d --remove-orphans worker
    }
    else {
        & $docker compose --progress quiet @composeArgs up -d --no-recreate worker
    }
    if (-not $?) {
        throw "Failed to start TimelineForAudio worker."
    }
}

& $docker compose @composeArgs exec -T worker python -m timeline_for_audio_worker @CliArgs
exit (Get-TfaLastExitCode)
