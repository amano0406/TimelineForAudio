[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$CliArgs
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = $PSScriptRoot
. (Join-Path $repoRoot "scripts\docker-runtime.ps1")

function Test-TfaCliJsonRequested {
    param([string[]]$Arguments)

    return @($Arguments) -contains "--json"
}

function Test-TfaTextLooksLikeJson {
    param([string]$Text)

    $trimmed = ([string]$Text).Trim()
    return $trimmed.StartsWith("{") -or $trimmed.StartsWith("[")
}

function Write-TfaJsonWorkerError {
    param(
        [int]$ExitCode,
        [string]$Stdout,
        [string]$Stderr
    )

    $message = ([string]$Stderr).Trim()
    if (-not $message) {
        $message = ([string]$Stdout).Trim()
    }
    if (-not $message) {
        $message = "TimelineForAudio Docker worker invocation failed."
    }
    $payload = [ordered]@{
        ok = $false
        error = [ordered]@{
            type = "DockerWorkerInvocationError"
            message = $message
            exit_code = $ExitCode
        }
    }
    [Console]::Out.WriteLine(($payload | ConvertTo-Json -Depth 6))
}

$jsonRequested = Test-TfaCliJsonRequested -Arguments $CliArgs

try {
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

$cliResult = Invoke-TfaHiddenProcess -FilePath $docker -Arguments (@("compose") + $composeArgs + @("exec", "-T", "worker", "python", "-m", "timeline_for_audio_worker") + @($CliArgs)) -WorkingDirectory $repoRoot
$exitCode = $cliResult.ExitCode
if ($exitCode -eq 0) {
    if ($cliResult.Stdout.Length -gt 0) {
        [Console]::Out.Write($cliResult.Stdout)
    }
    if ($cliResult.Stderr.Length -gt 0) {
        [Console]::Error.Write($cliResult.Stderr)
    }
    exit 0
}

if ($jsonRequested) {
    if (Test-TfaTextLooksLikeJson -Text $cliResult.Stdout) {
        [Console]::Out.Write($cliResult.Stdout)
    }
    else {
        Write-TfaJsonWorkerError -ExitCode $exitCode -Stdout $cliResult.Stdout -Stderr $cliResult.Stderr
    }
}
else {
    if ($cliResult.Stdout.Length -gt 0) {
        [Console]::Out.Write($cliResult.Stdout)
    }
    if ($cliResult.Stderr.Length -gt 0) {
        [Console]::Error.Write($cliResult.Stderr)
    }
    [Console]::Error.WriteLine("TimelineForAudio CLI failed while invoking the Docker worker. Exit code: $exitCode")
    [Console]::Error.WriteLine("Run the same command from C:\apps\TimelineForAudio with .\cli.ps1 to inspect Docker worker output and settings.")
}
exit $exitCode
}
catch {
    if ($jsonRequested) {
        Write-TfaJsonWorkerError -ExitCode 1 -Stdout "" -Stderr ([string]$_.Exception.Message)
    }
    else {
        [Console]::Error.WriteLine("error: $($_.Exception.Message)")
    }
    exit 1
}
