Set-StrictMode -Version Latest

$script:TfaDockerCommand = $null
$script:TfaDefaultApiPort = 19100

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

function Format-TfaProcessArgument {
    param([string]$Value)

    if ($null -eq $Value) {
        return '""'
    }
    $text = [string]$Value
    if ($text.Length -eq 0) {
        return '""'
    }
    if ($text -notmatch '[\s"]') {
        return $text
    }

    $builder = [System.Text.StringBuilder]::new()
    [void]$builder.Append('"')
    $backslashes = 0
    foreach ($character in $text.ToCharArray()) {
        if ($character -eq '\') {
            $backslashes += 1
            continue
        }
        if ($character -eq '"') {
            if ($backslashes -gt 0) {
                [void]$builder.Append(('\' * ($backslashes * 2)))
                $backslashes = 0
            }
            [void]$builder.Append('\"')
            continue
        }
        if ($backslashes -gt 0) {
            [void]$builder.Append(('\' * $backslashes))
            $backslashes = 0
        }
        [void]$builder.Append($character)
    }
    if ($backslashes -gt 0) {
        [void]$builder.Append(('\' * ($backslashes * 2)))
    }
    [void]$builder.Append('"')
    return $builder.ToString()
}

function Invoke-TfaHiddenProcess {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$Arguments = @(),
        [string]$WorkingDirectory = (Get-Location).Path,
        [switch]$WriteOutput,
        [switch]$SuppressOutput
    )

    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $FilePath
    $startInfo.Arguments = (@($Arguments) | ForEach-Object { Format-TfaProcessArgument -Value ([string]$_) }) -join " "
    $startInfo.WorkingDirectory = $WorkingDirectory
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.StandardOutputEncoding = [System.Text.UTF8Encoding]::new($false)
    $startInfo.StandardErrorEncoding = [System.Text.UTF8Encoding]::new($false)
    $fileDirectory = Split-Path -Parent $FilePath
    if ($fileDirectory) {
        $currentPath = $startInfo.EnvironmentVariables["PATH"]
        if (-not $currentPath) {
            $currentPath = $env:PATH
        }
        $updatedPath = "$fileDirectory;$currentPath"
        $startInfo.EnvironmentVariables["PATH"] = $updatedPath
        $startInfo.EnvironmentVariables["Path"] = $updatedPath
    }
    $startInfo.EnvironmentVariables["PATHEXT"] = ".COM;.EXE;.BAT;.CMD;.VBS;.VBE;.JS;.JSE;.WSF;.WSH;.MSC;.CPL"
    foreach ($name in @(
        "COMPOSE_PROJECT_NAME",
        "TIMELINE_FOR_AUDIO_HOST_SETTINGS_PATH",
        "TIMELINE_FOR_AUDIO_PATHS_OVERRIDE_PATH",
        "TIMELINE_FOR_AUDIO_INSTANCE_NAME",
        "TIMELINE_FOR_AUDIO_API_PORT"
    )) {
        $value = switch ($name) {
            "COMPOSE_PROJECT_NAME" { $env:COMPOSE_PROJECT_NAME }
            "TIMELINE_FOR_AUDIO_HOST_SETTINGS_PATH" { $env:TIMELINE_FOR_AUDIO_HOST_SETTINGS_PATH }
            "TIMELINE_FOR_AUDIO_PATHS_OVERRIDE_PATH" { $env:TIMELINE_FOR_AUDIO_PATHS_OVERRIDE_PATH }
            "TIMELINE_FOR_AUDIO_INSTANCE_NAME" { $env:TIMELINE_FOR_AUDIO_INSTANCE_NAME }
            "TIMELINE_FOR_AUDIO_API_PORT" { $env:TIMELINE_FOR_AUDIO_API_PORT }
        }
        if ($null -ne $value) {
            $startInfo.EnvironmentVariables[$name] = $value
        }
    }

    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    [void]$process.Start()
    $stdoutTask = $process.StandardOutput.ReadToEndAsync()
    $stderrTask = $process.StandardError.ReadToEndAsync()
    $process.WaitForExit()

    $stdout = [string]$stdoutTask.Result
    $stderr = [string]$stderrTask.Result
    if ($WriteOutput -and -not $SuppressOutput) {
        if ($stdout.Length -gt 0) {
            [Console]::Out.Write($stdout)
        }
        if ($stderr.Length -gt 0) {
            [Console]::Error.Write($stderr)
        }
    }

    return [pscustomobject]@{
        ExitCode = [int]$process.ExitCode
        Stdout = $stdout
        Stderr = $stderr
    }
}

function Invoke-TfaDocker {
    param(
        [string[]]$Arguments,
        [switch]$WriteOutput,
        [switch]$SuppressOutput
    )

    return Invoke-TfaHiddenProcess `
        -FilePath (Get-TfaDockerCommand) `
        -Arguments $Arguments `
        -WorkingDirectory (Get-Location).Path `
        -WriteOutput:$WriteOutput `
        -SuppressOutput:$SuppressOutput
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
        $result = Invoke-TfaDocker -Arguments @("info") -SuppressOutput
        if ($result.ExitCode -eq 0) {
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

    $dockerInfo = Invoke-TfaDocker -Arguments @("info") -SuppressOutput
    if ($dockerInfo.ExitCode -eq 0) {
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

    Initialize-TfaRuntimeSettings -RepoRoot $RepoRoot | Out-Null

    $pathScript = Join-Path $RepoRoot "scripts\prepare-docker-paths.ps1"
    $settingsOverridePath = [string]$env:TIMELINE_FOR_AUDIO_HOST_SETTINGS_PATH
    if ($settingsOverridePath) {
        & $pathScript -RepoRoot $RepoRoot -SettingsPath $settingsOverridePath | Out-Null
        return
    }
    & $pathScript -RepoRoot $RepoRoot | Out-Null
}

function ConvertTo-TfaInstanceName {
    param([object]$Value)

    $text = ([string]$Value).Trim().ToLowerInvariant()
    if ($text.StartsWith("local-")) {
        $text = $text.Substring("local-".Length)
    }
    $text = $text -replace '[^a-z0-9-]+', '-'
    $text = $text -replace '-+', '-'
    return $text.Trim("-")
}

function New-TfaRuntimeInstanceName {
    return ([guid]::NewGuid().ToString("N")).Substring(0, 10)
}

function ConvertTo-TfaApiPort {
    param(
        [object]$Value,
        [int]$Fallback = $script:TfaDefaultApiPort
    )

    $port = 0
    if (-not [int]::TryParse(([string]$Value).Trim(), [ref]$port)) {
        return $Fallback
    }
    if ($port -lt 1 -or $port -gt 65535) {
        return $Fallback
    }
    return $port
}

function Test-TfaJsonProperty {
    param(
        [object]$Payload,
        [Parameter(Mandatory = $true)][string]$Name
    )

    if ($null -eq $Payload) {
        return $false
    }
    return $Payload.PSObject.Properties.Name -contains $Name
}

function Get-TfaJsonPropertyValue {
    param(
        [object]$Payload,
        [Parameter(Mandatory = $true)][string]$Name,
        [object]$Fallback = $null
    )

    if (Test-TfaJsonProperty -Payload $Payload -Name $Name) {
        return $Payload.PSObject.Properties[$Name].Value
    }
    return $Fallback
}

function Get-TfaSettingsPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot
    )

    $settingsPath = [string]$env:TIMELINE_FOR_AUDIO_HOST_SETTINGS_PATH
    if ([string]::IsNullOrWhiteSpace($settingsPath)) {
        $settingsPath = Join-Path $RepoRoot "settings.json"
    }
    return [System.IO.Path]::GetFullPath($settingsPath)
}

function Read-TfaJsonPayload {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return $null
    }
    return Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
}

function ConvertTo-TfaSettingsPayload {
    param(
        [object]$Payload,
        [string]$InstanceName,
        [int]$ApiPort
    )

    $schemaVersion = Get-TfaJsonPropertyValue -Payload $Payload -Name "schemaVersion" -Fallback 1
    if ($schemaVersion -isnot [int]) {
        $schemaVersion = 1
    }

    $inputRoots = @()
    foreach ($root in @(Get-TfaJsonPropertyValue -Payload $Payload -Name "inputRoots" -Fallback @())) {
        $rootText = ([string]$root).Trim()
        if ($rootText) {
            $inputRoots += $rootText
        }
    }

    $outputRoot = ([string](Get-TfaJsonPropertyValue -Payload $Payload -Name "outputRoot" -Fallback "")).Trim()

    $token = ""
    if (Test-TfaJsonProperty -Payload $Payload -Name "huggingFaceToken") {
        $token = ([string]$Payload.huggingFaceToken).Trim()
    }
    elseif (Test-TfaJsonProperty -Payload $Payload -Name "huggingfaceToken") {
        $token = ([string]$Payload.huggingfaceToken).Trim()
    }

    $computeMode = ([string](Get-TfaJsonPropertyValue -Payload $Payload -Name "computeMode" -Fallback "cpu")).Trim().ToLowerInvariant()
    if ($computeMode -notin @("cpu", "gpu")) {
        $computeMode = "cpu"
    }

    return [ordered]@{
        schemaVersion = $schemaVersion
        inputRoots = @($inputRoots)
        outputRoot = $outputRoot
        huggingFaceToken = $token
        computeMode = $computeMode
        runtime = [ordered]@{
            instanceName = $InstanceName
            apiPort = $ApiPort
        }
    }
}

function Initialize-TfaRuntimeSettings {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot
    )

    $settingsPath = Get-TfaSettingsPath -RepoRoot $RepoRoot
    $settingsExamplePath = Join-Path $RepoRoot "settings.example.json"
    $sourcePath = if (Test-Path -LiteralPath $settingsPath) {
        $settingsPath
    }
    elseif (Test-Path -LiteralPath $settingsExamplePath) {
        $settingsExamplePath
    }
    else {
        $settingsPath
    }

    $payload = Read-TfaJsonPayload -Path $sourcePath
    $runtimePayload = Get-TfaJsonPropertyValue -Payload $payload -Name "runtime" -Fallback $null
    $instanceName = ConvertTo-TfaInstanceName -Value (Get-TfaJsonPropertyValue -Payload $runtimePayload -Name "instanceName" -Fallback "")
    if ([string]::IsNullOrWhiteSpace($instanceName)) {
        $instanceName = New-TfaRuntimeInstanceName
    }
    $apiPort = ConvertTo-TfaApiPort -Value (Get-TfaJsonPropertyValue -Payload $runtimePayload -Name "apiPort" -Fallback $script:TfaDefaultApiPort)

    $cleaned = ConvertTo-TfaSettingsPayload -Payload $payload -InstanceName $instanceName -ApiPort $apiPort
    $settingsDirectory = Split-Path -Parent $settingsPath
    if ($settingsDirectory) {
        New-Item -ItemType Directory -Path $settingsDirectory -Force | Out-Null
    }
    [System.IO.File]::WriteAllText(
        $settingsPath,
        (ConvertTo-Json -InputObject $cleaned -Depth 8),
        [System.Text.UTF8Encoding]::new($false)
    )

    $composeProject = [string]$env:COMPOSE_PROJECT_NAME
    if ([string]::IsNullOrWhiteSpace($composeProject)) {
        $composeProject = "timeline-for-audio-$instanceName"
    }

    $env:TIMELINE_FOR_AUDIO_INSTANCE_NAME = $instanceName
    $env:TIMELINE_FOR_AUDIO_API_PORT = [string]$apiPort

    return [pscustomobject]@{
        InstanceName = $instanceName
        ApiPort = $apiPort
        ComposeProject = $composeProject
        SettingsPath = $settingsPath
    }
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

    $result = Invoke-TfaHiddenProcess -FilePath $nvidia -Arguments @("--query-gpu=name", "--format=csv,noheader") -SuppressOutput
    return $result.ExitCode -eq 0
}

function Get-TfaComputeMode {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot
    )

    $settingsPath = [string]$env:TIMELINE_FOR_AUDIO_HOST_SETTINGS_PATH
    if (-not $settingsPath) {
        $settingsPath = Join-Path $RepoRoot "settings.json"
    }
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
    if ($command -in @("files", "items")) {
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

    $runtime = Initialize-TfaRuntimeSettings -RepoRoot $RepoRoot
    $args = [System.Collections.Generic.List[string]]::new()
    $args.Add("-p")
    $args.Add([string]$runtime.ComposeProject)
    $args.Add("-f")
    $args.Add((Join-Path $RepoRoot "docker-compose.yml"))

    $pathsOverride = [string]$env:TIMELINE_FOR_AUDIO_PATHS_OVERRIDE_PATH
    if (-not $pathsOverride) {
        $pathsOverride = Join-Path $RepoRoot ".docker\docker-compose.paths.yml"
    }
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
    $psResult = Invoke-TfaHiddenProcess -FilePath $docker -Arguments (@("compose") + $ComposeArgs + @("ps", "-q", "worker")) -WorkingDirectory $RepoRoot -SuppressOutput
    if ($psResult.ExitCode -ne 0) {
        return $null
    }
    $containerId = @($psResult.Stdout -split "\r?\n" | Where-Object { $_ } | Select-Object -First 1)
    if (-not $containerId) {
        return $null
    }

    $inspectResult = Invoke-TfaHiddenProcess -FilePath $docker -Arguments @("inspect", $containerId, "--format", "{{range .Config.Env}}{{println .}}{{end}}") -WorkingDirectory $RepoRoot -SuppressOutput
    if ($inspectResult.ExitCode -ne 0) {
        return $null
    }

    $envRows = $inspectResult.Stdout -split "\r?\n"
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
