[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = $PSScriptRoot
. (Join-Path $repoRoot "scripts\docker-runtime.ps1")

$apiPidFile = Join-Path $repoRoot ".runtime\api.pid"

function Stop-TfaNativeApi {
    if (-not (Test-Path -LiteralPath $apiPidFile)) {
        return
    }

    $pidText = (Get-Content -LiteralPath $apiPidFile -Raw).Trim()
    $pidValue = 0
    if ([int]::TryParse($pidText, [ref]$pidValue)) {
        $process = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
        if ($null -ne $process) {
            Stop-Process -Id $pidValue -Force -ErrorAction SilentlyContinue
        }
    }

    Remove-Item -LiteralPath $apiPidFile -Force -ErrorAction SilentlyContinue
}

Stop-TfaNativeApi

Initialize-TfaDocker -RepoRoot $repoRoot
$composeArgs = Get-TfaComposeArgs -RepoRoot $repoRoot
$docker = Get-TfaDockerCommand

Invoke-TfaWithFileLock -RepoRoot $repoRoot -LockName "docker-compose.lock" -ScriptBlock {
    $script:TfaStopResult = Invoke-TfaHiddenProcess -FilePath $docker -Arguments (@("compose") + $composeArgs + @("down", "--remove-orphans")) -WorkingDirectory $repoRoot -WriteOutput
}
exit ([int]$script:TfaStopResult.ExitCode)
