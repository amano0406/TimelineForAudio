[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = $PSScriptRoot
. (Join-Path $repoRoot "scripts\docker-runtime.ps1")

Initialize-TfaDocker -RepoRoot $repoRoot
$composeArgs = Get-TfaComposeArgs -RepoRoot $repoRoot
$docker = Get-TfaDockerCommand

Invoke-TfaWithFileLock -RepoRoot $repoRoot -LockName "docker-compose.lock" -ScriptBlock {
    $script:TfaStopResult = Invoke-TfaHiddenProcess -FilePath $docker -Arguments (@("compose") + $composeArgs + @("down", "--remove-orphans")) -WorkingDirectory $repoRoot -WriteOutput
}
exit ([int]$script:TfaStopResult.ExitCode)
