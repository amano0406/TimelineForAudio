Set-StrictMode -Version Latest

$script:TfaDockerCommand = $null

function Get-TfaLastExitCode {
    $variable = Get-Variable -Name LASTEXITCODE -Scope Global -ErrorAction SilentlyContinue
    if ($variable -and $null -ne $variable.Value) {
        return [int]$variable.Value
    }
    if ($?) {
        return 0
    }
    return 1
}

function Add-TfaDockerPath {
    $dockerBin = Join-Path $env:ProgramFiles "Docker\Docker\resources\bin"
    if (Test-Path -LiteralPath (Join-Path $dockerBin "docker.exe")) {
        $env:PATH = "$dockerBin;$env:PATH"
    }
}

function Resolve-TfaDockerCommand {
    $dockerExe = Join-Path $env:ProgramFiles "Docker\Docker\resources\bin\docker.exe"
    if (Test-Path -LiteralPath $dockerExe) {
        return $dockerExe
    }

    $dockerCommand = Get-Command docker.exe -ErrorAction SilentlyContinue
    if ($dockerCommand) {
        return $dockerCommand.Source
    }

    $dockerCommand = Get-Command docker -ErrorAction SilentlyContinue
    if ($dockerCommand) {
        return $dockerCommand.Source
    }

    return $null
}

function Get-TfaDockerCommand {
    if (-not $script:TfaDockerCommand) {
        $script:TfaDockerCommand = Resolve-TfaDockerCommand
    }
    if (-not $script:TfaDockerCommand) {
        throw "docker.exe was not found."
    }
    return $script:TfaDockerCommand
}

function Get-TfaDockerDesktopPath {
    $candidates = @(
        (Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"),
        (Join-Path $env:LocalAppData "Programs\Docker\Docker\Docker Desktop.exe")
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) {
            return $candidate
        }
    }
    return $null
}

function Wait-TfaDockerEngine {
    param(
        [int]$MaxAttempts = 60,
        [int]$SleepSeconds = 2
    )

    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt += 1) {
        & (Get-TfaDockerCommand) info *> $null
        if ($?) {
            return
        }
        Start-Sleep -Seconds $SleepSeconds
    }
    throw "Docker Desktop did not become ready in time."
}

function Initialize-TfaDocker {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot
    )

    Set-Location $RepoRoot
    Add-TfaDockerPath

    $dockerCommand = Resolve-TfaDockerCommand
    $script:TfaDockerCommand = $dockerCommand
    $dockerDesktop = Get-TfaDockerDesktopPath
    if (-not $dockerCommand) {
        if ($dockerDesktop) {
            Write-Host "Docker Desktop appears to be installed, but docker.exe is not available from this shell."
            Write-Host "Starting Docker Desktop. Reopen PowerShell if docker.exe is still unavailable."
            Start-Process -FilePath $dockerDesktop | Out-Null
        }
        else {
            Write-Host "Docker Desktop is not installed, or docker.exe is not on PATH."
            Write-Host "Download and install Docker Desktop:"
            Write-Host "  https://docs.docker.com/desktop/setup/install/windows-install/"
            Start-Process "https://docs.docker.com/desktop/setup/install/windows-install/" | Out-Null
        }
        exit 1
    }

    & (Get-TfaDockerCommand) info *> $null
    if ($?) {
        return
    }

    if ($dockerDesktop) {
        Write-Host "Starting Docker Desktop. This can take a minute..."
        Start-Process -FilePath $dockerDesktop | Out-Null
        Wait-TfaDockerEngine
        return
    }

    throw "Docker Desktop is installed but the Docker engine is not ready."
}

function Initialize-TfaLocalFiles {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot
    )

    $pathScript = Join-Path $RepoRoot "scripts\prepare-docker-paths.ps1"
    & $pathScript -RepoRoot $RepoRoot | Out-Null
}

function Get-TfaNvidiaSmiPath {
    $nvidia = Get-Command nvidia-smi -ErrorAction SilentlyContinue
    if ($nvidia) {
        return $nvidia.Source
    }

    $candidates = @()
    if ($env:ProgramFiles) {
        $candidates += Join-Path $env:ProgramFiles "NVIDIA Corporation\NVSMI\nvidia-smi.exe"
    }

    $programFilesX86 = [Environment]::GetFolderPath("ProgramFilesX86")
    if ($programFilesX86) {
        $candidates += Join-Path $programFilesX86 "NVIDIA Corporation\NVSMI\nvidia-smi.exe"
    }

    if ($env:SystemRoot) {
        $candidates += Join-Path $env:SystemRoot "System32\nvidia-smi.exe"
    }

    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) {
            return $candidate
        }
    }

    return $null
}

function Test-TfaNvidiaGpuAvailable {
    $nvidia = Get-TfaNvidiaSmiPath
    if (-not $nvidia) {
        return $false
    }

    & $nvidia --query-gpu=name --format=csv,noheader *> $null
    return [bool]$?
}

function Get-TfaComputeMode {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot
    )

    $settingsPath = Join-Path $RepoRoot "settings.json"
    if (-not (Test-Path -LiteralPath $settingsPath)) {
        $settingsPath = Join-Path $RepoRoot "settings.example.json"
    }

    $mode = "cpu"
    if (Test-Path -LiteralPath $settingsPath) {
        try {
            $payload = Get-Content -LiteralPath $settingsPath -Raw | ConvertFrom-Json
            if ($payload.PSObject.Properties.Name -contains "computeMode") {
                $mode = [string]$payload.computeMode
            }
        }
        catch {
            $mode = "cpu"
        }
    }

    $mode = $mode.Trim().ToLowerInvariant()
    if ($mode -notin @("cpu", "gpu")) {
        return "cpu"
    }
    return $mode
}

function Assert-TfaGpuAvailableIfRequested {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot
    )

    $mode = Get-TfaComputeMode -RepoRoot $RepoRoot
    if ($mode -ne "gpu") {
        return
    }

    if (Test-TfaNvidiaGpuAvailable) {
        return
    }

    throw "settings.json computeMode is gpu, but NVIDIA GPU is not available from this shell. Set computeMode to cpu or fix NVIDIA/Docker GPU support."
}

function Test-TfaCliRequiresConfiguredWorker {
    param(
        [string[]]$CliArgs
    )

    if (-not $CliArgs -or $CliArgs.Count -eq 0) {
        return $false
    }

    $command = [string]$CliArgs[0]
    if ($command -in @("process-run", "daemon")) {
        return $true
    }
    if ($command -eq "items" -and $CliArgs.Count -ge 2 -and ([string]$CliArgs[1]) -eq "refresh") {
        return $true
    }
    return $false
}

function Get-TfaComposeArgs {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot,
        [switch]$IncludeGpu
    )

    $args = [System.Collections.Generic.List[string]]::new()
    $args.Add("-f")
    $args.Add((Join-Path $RepoRoot "docker-compose.yml"))

    $pathsOverride = Join-Path $RepoRoot ".docker\docker-compose.paths.yml"
    if (Test-Path -LiteralPath $pathsOverride) {
        $args.Add("-f")
        $args.Add($pathsOverride)
    }

    if ($IncludeGpu -and ((Get-TfaComputeMode -RepoRoot $RepoRoot) -eq "gpu") -and (Test-TfaNvidiaGpuAvailable)) {
        $args.Add("-f")
        $args.Add((Join-Path $RepoRoot "docker-compose.gpu.yml"))
    }

    return $args.ToArray()
}

function Get-TfaDesiredWorkerFlavor {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot
    )

    return Get-TfaComputeMode -RepoRoot $RepoRoot
}

function Get-TfaCurrentWorkerFlavor {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot,
        [Parameter(Mandatory = $true)]
        [string[]]$ComposeArgs
    )

    $docker = Get-TfaDockerCommand
    $containerIds = & $docker compose @ComposeArgs ps -q worker 2>$null
    $containerId = @($containerIds | Select-Object -First 1)
    if (-not $containerId) {
        return $null
    }

    $envRows = & $docker inspect $containerId --format '{{range .Config.Env}}{{println .}}{{end}}' 2>$null
    if (-not $?) {
        return $null
    }

    foreach ($row in $envRows) {
        if ([string]$row -like "TIMELINE_FOR_AUDIO_WORKER_FLAVOR=*") {
            $value = ([string]$row).Substring("TIMELINE_FOR_AUDIO_WORKER_FLAVOR=".Length)
            $value = $value.Trim().ToLowerInvariant()
            if ($value -in @("cpu", "gpu")) {
                return $value
            }
        }
    }

    return $null
}

function Test-TfaWorkerFlavorMismatch {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot,
        [Parameter(Mandatory = $true)]
        [string[]]$ComposeArgs
    )

    $desired = Get-TfaDesiredWorkerFlavor -RepoRoot $RepoRoot
    $current = Get-TfaCurrentWorkerFlavor -RepoRoot $RepoRoot -ComposeArgs $ComposeArgs
    return ($current -and ($current -ne $desired))
}

function Invoke-TfaWithFileLock {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot,
        [Parameter(Mandatory = $true)]
        [string]$LockName,
        [Parameter(Mandatory = $true)]
        [scriptblock]$ScriptBlock
    )

    $generatedDir = Join-Path $RepoRoot ".docker"
    New-Item -ItemType Directory -Path $generatedDir -Force | Out-Null
    $lockPath = Join-Path $generatedDir $LockName
    $lockStream = $null

    for ($attempt = 1; $attempt -le 300; $attempt += 1) {
        try {
            $lockStream = [System.IO.File]::Open(
                $lockPath,
                [System.IO.FileMode]::OpenOrCreate,
                [System.IO.FileAccess]::ReadWrite,
                [System.IO.FileShare]::None
            )
            break
        }
        catch [System.IO.IOException] {
            Start-Sleep -Milliseconds 100
        }
    }
    if (-not $lockStream) {
        throw "Timed out waiting for lock: $lockPath"
    }

    try {
        & $ScriptBlock
    }
    finally {
        if ($lockStream) {
            $lockStream.Dispose()
        }
    }
}
