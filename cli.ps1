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

function Test-TfaItemsDownloadCommand {
    param([string[]]$Arguments)

    return @($Arguments).Count -ge 2 -and $Arguments[0] -eq "items" -and $Arguments[1] -eq "download"
}

function Get-TfaOutputArgumentValue {
    param([string[]]$Arguments)

    for ($index = 0; $index -lt @($Arguments).Count; $index += 1) {
        $value = [string]$Arguments[$index]
        if ($value -eq "--output") {
            if (($index + 1) -ge @($Arguments).Count) {
                return $null
            }
            return [string]$Arguments[$index + 1]
        }
        if ($value.StartsWith("--output=")) {
            return $value.Substring("--output=".Length)
        }
    }
    return $null
}

function Remove-TfaOutputArgument {
    param([string[]]$Arguments)

    $rows = [System.Collections.Generic.List[string]]::new()
    for ($index = 0; $index -lt @($Arguments).Count; $index += 1) {
        $value = [string]$Arguments[$index]
        if ($value -eq "--output") {
            $index += 1
            continue
        }
        if ($value.StartsWith("--output=")) {
            continue
        }
        $rows.Add($value) | Out-Null
    }
    return [string[]]$rows.ToArray()
}

function Test-TfaHostOutputPath {
    param([string]$PathText)

    if ([string]::IsNullOrWhiteSpace($PathText)) {
        return $false
    }

    $trimmed = $PathText.Trim()
    if ($trimmed.StartsWith("/")) {
        return $false
    }
    return $true
}

function ConvertFrom-TfaJsonObject {
    param([string]$Text)

    $trimmed = ([string]$Text).Trim()
    $jsonStart = $trimmed.IndexOf("{")
    $jsonEnd = $trimmed.LastIndexOf("}")
    if ($jsonStart -lt 0 -or $jsonEnd -lt $jsonStart) {
        throw "TimelineForAudio worker did not return a JSON object."
    }
    return $trimmed.Substring($jsonStart, $jsonEnd - $jsonStart + 1) | ConvertFrom-Json
}

function Convert-TfaContainerPathToHostPath {
    param([string]$PathText)

    $text = ([string]$PathText).Trim()
    if (-not $text) {
        return $text
    }
    if ($text -match '^[A-Za-z]:[\\/]') {
        return [System.IO.Path]::GetFullPath($text)
    }

    $normalized = $text.Replace("\", "/")
    if ($normalized -eq "/workspace") {
        return $repoRoot
    }
    if ($normalized.StartsWith("/workspace/")) {
        $relativePath = $normalized.Substring("/workspace/".Length).Replace("/", [System.IO.Path]::DirectorySeparatorChar)
        return (Join-Path $repoRoot $relativePath)
    }

    return $text
}

function Complete-TfaHostDownloadOutput {
    param(
        [string]$WorkerStdout,
        [string]$RequestedOutputPath
    )

    $payload = ConvertFrom-TfaJsonObject -Text $WorkerStdout
    $archivePathText = [string]$payload.archive_path
    if ([string]::IsNullOrWhiteSpace($archivePathText)) {
        throw "TimelineForAudio worker did not return archive_path."
    }

    $sourceHostPath = Convert-TfaContainerPathToHostPath -PathText $archivePathText
    if (-not (Test-Path -LiteralPath $sourceHostPath)) {
        throw "TimelineForAudio worker created archive in an unmapped path: $archivePathText"
    }

    $requestedFullPath = [System.IO.Path]::GetFullPath($RequestedOutputPath)
    $requestedParent = Split-Path -Parent $requestedFullPath
    if ($requestedParent -and -not (Test-Path -LiteralPath $requestedParent)) {
        New-Item -ItemType Directory -Path $requestedParent | Out-Null
    }

    if (-not ([System.String]::Equals($sourceHostPath, $requestedFullPath, [System.StringComparison]::OrdinalIgnoreCase))) {
        Copy-Item -LiteralPath $sourceHostPath -Destination $requestedFullPath -Force
        Remove-Item -LiteralPath $sourceHostPath -Force -ErrorAction SilentlyContinue
    }

    $payload.archive_path = $requestedFullPath
    return $payload
}

function Write-TfaPayload {
    param(
        [object]$Payload,
        [bool]$AsJson
    )

    if ($AsJson) {
        [Console]::Out.WriteLine(($Payload | ConvertTo-Json -Depth 12))
        return
    }

    foreach ($property in $Payload.PSObject.Properties) {
        [Console]::Out.WriteLine("$($property.Name): $($property.Value)")
    }
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
$hostDownloadOutput = $null
$workerCliArgs = [string[]]$CliArgs
if (Test-TfaItemsDownloadCommand -Arguments $CliArgs) {
    $requestedOutput = Get-TfaOutputArgumentValue -Arguments $CliArgs
    if (Test-TfaHostOutputPath -PathText $requestedOutput) {
        $hostDownloadOutput = $requestedOutput
        $workerCliArgs = Remove-TfaOutputArgument -Arguments $CliArgs
        if (-not (Test-TfaCliJsonRequested -Arguments $workerCliArgs)) {
            $workerCliArgs = @($workerCliArgs) + "--json"
        }
    }
}
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

$cliResult = Invoke-TfaHiddenProcess -FilePath $docker -Arguments (@("compose") + $composeArgs + @("exec", "-T", "worker", "python", "-m", "timeline_for_audio_worker") + @($workerCliArgs)) -WorkingDirectory $repoRoot
$exitCode = $cliResult.ExitCode
if ($exitCode -eq 0) {
    if ($hostDownloadOutput) {
        $downloadPayload = Complete-TfaHostDownloadOutput -WorkerStdout $cliResult.Stdout -RequestedOutputPath $hostDownloadOutput
        Write-TfaPayload -Payload $downloadPayload -AsJson:$jsonRequested
        if ($cliResult.Stderr.Length -gt 0) {
            [Console]::Error.Write($cliResult.Stderr)
        }
        exit 0
    }
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
