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
$apiPidFile = Join-Path $runtimeDir "api.pid"
$apiProject = Join-Path $repoRoot "api\TimelineForAudio.Api.csproj"

New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null

function Test-TfaApiCommandLine {
    param([string]$CommandLine)

    if (-not $CommandLine) {
        return $false
    }

    $escapedRepoRoot = [regex]::Escape($repoRoot)
    return (
        ($CommandLine -match "TimelineForAudio\.Api(\.csproj|\.dll|\.exe)?") -and
        ($CommandLine -match $escapedRepoRoot)
    )
}

function Get-TfaApiProcess {
    try {
        $matches = @(
            Get-CimInstance Win32_Process -ErrorAction Stop |
                Where-Object { Test-TfaApiCommandLine -CommandLine ([string]$_.CommandLine) }
        )
    }
    catch {
        return $null
    }

    if ($matches.Count -eq 0) {
        return $null
    }

    $projectHost = @($matches | Where-Object { [string]$_.CommandLine -match "TimelineForAudio\.Api\.csproj" } | Select-Object -First 1)
    if ($projectHost.Count -gt 0) {
        return $projectHost[0]
    }

    return ($matches | Select-Object -First 1)
}

function Start-TfaNativeApi {
    param(
        [int]$ApiPort,
        [switch]$RunInForeground
    )

    if (-not (Test-Path -LiteralPath $apiProject -PathType Leaf)) {
        throw "TimelineForAudio API project was not found: $apiProject"
    }

    if (Test-Path -LiteralPath $apiPidFile) {
        $existingPidText = (Get-Content -LiteralPath $apiPidFile -Raw).Trim()
        $existingPid = 0
        if ([int]::TryParse($existingPidText, [ref]$existingPid)) {
            $existing = Get-Process -Id $existingPid -ErrorAction SilentlyContinue
            if ($null -ne $existing) {
                $commandLine = ""
                try {
                    $cim = Get-CimInstance Win32_Process -Filter "ProcessId = $existingPid"
                    if ($null -ne $cim) {
                        $commandLine = [string]$cim.CommandLine
                    }
                }
                catch {
                    $commandLine = ""
                }
                if (Test-TfaApiCommandLine -CommandLine $commandLine) {
                    Write-Host "TimelineForAudio API is already running. pid=$existingPid"
                    return
                }
            }
        }
        Remove-Item -LiteralPath $apiPidFile -Force
    }

    $running = Get-TfaApiProcess
    if ($null -ne $running) {
        Set-Content -LiteralPath $apiPidFile -Value ([string]$running.ProcessId) -Encoding ASCII
        Write-Host "TimelineForAudio API is already running. pid=$($running.ProcessId)"
        return
    }

    $apiArgs = @(
        "run",
        "--project",
        $apiProject,
        "--no-launch-profile",
        "--",
        "--product-root",
        $repoRoot,
        "--port",
        [string]$ApiPort
    )

    if ($RunInForeground) {
        & dotnet @apiArgs
        exit $LASTEXITCODE
    }

    $process = Start-Process -FilePath "dotnet" -ArgumentList $apiArgs -WorkingDirectory $repoRoot -WindowStyle Hidden -PassThru
    Set-Content -LiteralPath $apiPidFile -Value ([string]$process.Id) -Encoding ASCII
    Write-Host "TimelineForAudio API started. pid=$($process.Id)"
}

Initialize-TfaDocker -RepoRoot $repoRoot
Initialize-TfaLocalFiles -RepoRoot $repoRoot
Assert-TfaGpuAvailableIfRequested -RepoRoot $repoRoot

$runtime = Initialize-TfaRuntimeSettings -RepoRoot $repoRoot
if ($Port -gt 0) {
    $runtime.ApiPort = $Port
    $env:TIMELINE_FOR_AUDIO_API_PORT = [string]$Port
}
$composeArgs = Get-TfaComposeArgs -RepoRoot $repoRoot -IncludeGpu
$docker = Get-TfaDockerCommand
$computeMode = Get-TfaComputeMode -RepoRoot $repoRoot
Write-Host "Compute mode: $computeMode"
if ($computeMode -eq "gpu") {
    Write-Host "Starting GPU worker image."
}

Write-Host "Starting the worker container..."
Invoke-TfaWithFileLock -RepoRoot $repoRoot -LockName "docker-compose.lock" -ScriptBlock {
    $upArgs = @("compose") + $composeArgs + @("up", "-d", "--remove-orphans")
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

Start-TfaNativeApi -ApiPort ([int]$runtime.ApiPort) -RunInForeground:$Foreground

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
