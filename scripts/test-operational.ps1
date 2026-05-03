[CmdletBinding()]
param(
    [Parameter()]
    [switch]$UseRealModels,

    [Parameter()]
    [switch]$KeepOutput,

    [Parameter()]
    [string]$WorkRoot = "C:\Codex\workspaces\TimelineForAudio\operational-tests"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$settingsPath = Join-Path $repoRoot "settings.json"
$settingsExamplePath = Join-Path $repoRoot "settings.example.json"
$cliPath = Join-Path $repoRoot "cli.ps1"
$preparePathsScript = Join-Path $repoRoot "scripts\prepare-docker-paths.ps1"

if ([System.IO.Path]::DirectorySeparatorChar -ne "\") {
    throw "This operational test must be run from Windows PowerShell."
}
if (-not (Test-Path -LiteralPath $cliPath)) {
    throw "cli.ps1 was not found: $cliPath"
}

function ConvertFrom-TfaJsonOutput {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Text
    )

    $trimmed = $Text.Trim()
    if (-not $trimmed) {
        throw "Command returned no output."
    }

    $objectStart = $trimmed.IndexOf("{")
    $arrayStart = $trimmed.IndexOf("[")
    $starts = @(@($objectStart, $arrayStart) | Where-Object { $_ -ge 0 } | Sort-Object)
    if ($starts.Count -le 0) {
        throw "Command did not return JSON: $trimmed"
    }

    $start = [int]$starts[0]
    $objectEnd = $trimmed.LastIndexOf("}")
    $arrayEnd = $trimmed.LastIndexOf("]")
    $end = [Math]::Max($objectEnd, $arrayEnd)
    if ($end -lt $start) {
        throw "Command returned incomplete JSON: $trimmed"
    }

    return $trimmed.Substring($start, $end - $start + 1) | ConvertFrom-Json
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

function ConvertTo-TfaPowerShellLiteral {
    param([string]$Value)

    if ($null -eq $Value) {
        return "''"
    }
    return "'" + ([string]$Value).Replace("'", "''") + "'"
}

function Invoke-TfaPowerShellFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [string[]]$Arguments = @()
    )

    $powershellPath = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
    if (-not (Test-Path -LiteralPath $powershellPath)) {
        $powershellPath = "powershell.exe"
    }

    $envStatements = [System.Collections.Generic.List[string]]::new()
    foreach ($name in @(
        "COMPOSE_PROJECT_NAME",
        "TIMELINE_FOR_AUDIO_HOST_SETTINGS_PATH",
        "TIMELINE_FOR_AUDIO_PATHS_OVERRIDE_PATH"
    )) {
        $value = switch ($name) {
            "COMPOSE_PROJECT_NAME" { $env:COMPOSE_PROJECT_NAME }
            "TIMELINE_FOR_AUDIO_HOST_SETTINGS_PATH" { $env:TIMELINE_FOR_AUDIO_HOST_SETTINGS_PATH }
            "TIMELINE_FOR_AUDIO_PATHS_OVERRIDE_PATH" { $env:TIMELINE_FOR_AUDIO_PATHS_OVERRIDE_PATH }
        }
        if ($null -ne $value) {
            $envStatements.Add('$env:' + $name + ' = ' + (ConvertTo-TfaPowerShellLiteral -Value ([string]$value))) | Out-Null
        }
    }
    $callParts = [System.Collections.Generic.List[string]]::new()
    $callParts.Add("&") | Out-Null
    $callParts.Add((ConvertTo-TfaPowerShellLiteral -Value $FilePath)) | Out-Null
    foreach ($argument in @($Arguments)) {
        $callParts.Add((ConvertTo-TfaPowerShellLiteral -Value ([string]$argument))) | Out-Null
    }
    $commandText = ([string[]]$envStatements + @($callParts.ToArray() -join " ")) -join "; "

    $allArguments = @(
        "-NoLogo",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        $commandText
    )

    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $powershellPath
    $startInfo.Arguments = (@($allArguments) | ForEach-Object { Format-TfaProcessArgument -Value ([string]$_) }) -join " "
    $startInfo.WorkingDirectory = $repoRoot
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.StandardOutputEncoding = [System.Text.UTF8Encoding]::new($false)
    $startInfo.StandardErrorEncoding = [System.Text.UTF8Encoding]::new($false)
    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    [void]$process.Start()
    $stdoutTask = $process.StandardOutput.ReadToEndAsync()
    $stderrTask = $process.StandardError.ReadToEndAsync()
    $process.WaitForExit()

    return [pscustomobject]@{
        ExitCode = [int]$process.ExitCode
        Stdout = [string]$stdoutTask.Result
        Stderr = [string]$stderrTask.Result
    }
}

function Invoke-TfaCliJson {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    $result = Invoke-TfaPowerShellFile -FilePath $cliPath -Arguments $Arguments
    $rawOutput = [string]$result.Stdout
    if ($result.ExitCode -ne 0) {
        Write-Host $result.Stdout
        Write-Host $result.Stderr
        throw "cli.ps1 failed with exit code $($result.ExitCode). Arguments: $($Arguments -join ' ')"
    }
    return ConvertFrom-TfaJsonOutput -Text $rawOutput
}

function New-TfaOperationalWaveFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [double]$DurationSeconds = 3.0,
        [int]$SampleRate = 16000,
        [double]$FrequencyHz = 440.0
    )

    $samples = [int]($SampleRate * $DurationSeconds)
    $channels = 1
    $bitsPerSample = 16
    $blockAlign = [int]($channels * ($bitsPerSample / 8))
    $byteRate = [int]($SampleRate * $blockAlign)
    $dataLength = [int]($samples * $blockAlign)
    $encoding = [System.Text.Encoding]::ASCII

    New-Item -ItemType Directory -Path (Split-Path -Parent $Path) -Force | Out-Null
    $stream = [System.IO.File]::Create($Path)
    $writer = [System.IO.BinaryWriter]::new($stream)
    try {
        $writer.Write($encoding.GetBytes("RIFF"))
        $writer.Write([int](36 + $dataLength))
        $writer.Write($encoding.GetBytes("WAVE"))
        $writer.Write($encoding.GetBytes("fmt "))
        $writer.Write([int]16)
        $writer.Write([int16]1)
        $writer.Write([int16]$channels)
        $writer.Write([int]$SampleRate)
        $writer.Write([int]$byteRate)
        $writer.Write([int16]$blockAlign)
        $writer.Write([int16]$bitsPerSample)
        $writer.Write($encoding.GetBytes("data"))
        $writer.Write([int]$dataLength)

        for ($index = 0; $index -lt $samples; $index += 1) {
            $amplitude = [Math]::Sin((2.0 * [Math]::PI * $FrequencyHz * $index) / $SampleRate)
            $writer.Write([int16]([Math]::Round($amplitude * 16000)))
        }
    }
    finally {
        $writer.Dispose()
        $stream.Dispose()
    }
}

function Get-TfaOriginalSettings {
    if (Test-Path -LiteralPath $settingsPath) {
        return Get-Content -LiteralPath $settingsPath -Raw | ConvertFrom-Json
    }
    if (Test-Path -LiteralPath $settingsExamplePath) {
        return Get-Content -LiteralPath $settingsExamplePath -Raw | ConvertFrom-Json
    }
    return [pscustomobject]@{
        schemaVersion = 1
        inputRoots = @()
        outputRoot = ""
        huggingfaceToken = ""
        computeMode = "cpu"
    }
}

function Test-TfaZipContains {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ArchivePath,
        [Parameter(Mandatory = $true)]
        [string]$Pattern
    )

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [System.IO.Compression.ZipFile]::OpenRead($ArchivePath)
    try {
        foreach ($entry in $zip.Entries) {
            if ($entry.FullName -like $Pattern) {
                return $true
            }
        }
        return $false
    }
    finally {
        $zip.Dispose()
    }
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$runId = "operational-$timestamp-$(([guid]::NewGuid().ToString('N')).Substring(0, 8))"
$runRoot = Join-Path $WorkRoot $runId
$inputRoot = Join-Path $runRoot "input"
$outputRoot = Join-Path $runRoot "output"
$samplePath = Join-Path $inputRoot "operational-sample.wav"
$testSettingsPath = Join-Path $runRoot "settings.json"
$testPathsOverridePath = Join-Path $runRoot "docker-compose.paths.yml"
$originalComposeProjectName = $env:COMPOSE_PROJECT_NAME
$originalHostSettingsPath = $env:TIMELINE_FOR_AUDIO_HOST_SETTINGS_PATH
$originalPathsOverridePath = $env:TIMELINE_FOR_AUDIO_PATHS_OVERRIDE_PATH
$projectName = "timeline-for-audio-operational-$($runId.ToLowerInvariant() -replace '[^a-z0-9-]', '-')"

New-Item -ItemType Directory -Path $runRoot, $inputRoot, $outputRoot -Force | Out-Null
New-TfaOperationalWaveFile -Path $samplePath

$originalSettings = Get-TfaOriginalSettings
$computeMode = "cpu"
if ($UseRealModels) {
    $token = ""
    if ($originalSettings.PSObject.Properties.Name -contains "huggingfaceToken") {
        $token = [string]$originalSettings.huggingfaceToken
    }
    if ([string]::IsNullOrWhiteSpace($token)) {
        throw "UseRealModels requires huggingfaceToken in the current settings.json."
    }
}
else {
    $token = "hf_operational_test_placeholder_000000"
}

$testSettings = [ordered]@{
    schemaVersion = 1
    inputRoots = @($inputRoot)
    outputRoot = $outputRoot
    huggingfaceToken = $token
    computeMode = $computeMode
}

try {
    [System.IO.File]::WriteAllText(
        $testSettingsPath,
        (ConvertTo-Json -InputObject $testSettings -Depth 8),
        [System.Text.UTF8Encoding]::new($false)
    )
    $env:COMPOSE_PROJECT_NAME = $projectName
    $env:TIMELINE_FOR_AUDIO_HOST_SETTINGS_PATH = $testSettingsPath
    $env:TIMELINE_FOR_AUDIO_PATHS_OVERRIDE_PATH = $testPathsOverridePath

    $envProbeScript = Join-Path $runRoot "probe-env.ps1"
    [System.IO.File]::WriteAllText(
        $envProbeScript,
        @'
[pscustomobject]@{
  COMPOSE_PROJECT_NAME = $env:COMPOSE_PROJECT_NAME
  TIMELINE_FOR_AUDIO_HOST_SETTINGS_PATH = $env:TIMELINE_FOR_AUDIO_HOST_SETTINGS_PATH
  TIMELINE_FOR_AUDIO_PATHS_OVERRIDE_PATH = $env:TIMELINE_FOR_AUDIO_PATHS_OVERRIDE_PATH
} | ConvertTo-Json -Compress
'@,
        [System.Text.UTF8Encoding]::new($false)
    )
    $envProbe = Invoke-TfaPowerShellFile -FilePath $envProbeScript
    if ($envProbe.ExitCode -ne 0) {
        throw "Failed to verify operational test environment propagation."
    }
    $envProbePayload = ConvertFrom-TfaJsonOutput -Text $envProbe.Stdout
    if ([string]$envProbePayload.TIMELINE_FOR_AUDIO_HOST_SETTINGS_PATH -ne $testSettingsPath) {
        throw "Operational test environment was not propagated to child PowerShell."
    }

    Write-Host "Running isolated operational test."
    Write-Host "  Work root: $runRoot"
    Write-Host "  Real models: $UseRealModels"

    $status = Invoke-TfaCliJson -Arguments @("settings", "status", "--json")
    if ([string]$status.setup.state -ne "ready") {
        throw "settings status was not ready: $($status | ConvertTo-Json -Depth 8)"
    }

    $files = Invoke-TfaCliJson -Arguments @("files", "list", "--json")
    if ([int]$files.total_files -ne 1) {
        throw "files list did not return exactly one test file: $($files | ConvertTo-Json -Depth 8)"
    }

    if ($UseRealModels) {
        $refresh = Invoke-TfaCliJson -Arguments @("items", "refresh", "--max-items", "1", "--json")
        if ([string]$refresh.state -notin @("completed", "failed")) {
            throw "items refresh returned an unexpected state: $($refresh | ConvertTo-Json -Depth 12)"
        }
        if ([string]$refresh.state -eq "failed") {
            throw "items refresh failed: $($refresh | ConvertTo-Json -Depth 12)"
        }

        $items = Invoke-TfaCliJson -Arguments @("items", "list", "--json")
        if ([int]$items.total_items -lt 1) {
            throw "items list returned no completed items."
        }

        $download = Invoke-TfaCliJson -Arguments @("items", "download", "--json")
        $archivePath = [string]$download.archive_path
        if (-not (Test-Path -LiteralPath $archivePath -PathType Leaf)) {
            throw "items download archive was not created: $archivePath"
        }
        if (-not (Test-TfaZipContains -ArchivePath $archivePath -Pattern "README.md")) {
            throw "download archive does not contain README.md."
        }
        if (-not (Test-TfaZipContains -ArchivePath $archivePath -Pattern "items/*/timeline.json")) {
            throw "download archive does not contain timeline.json."
        }
        if (-not (Test-TfaZipContains -ArchivePath $archivePath -Pattern "items/*/convert_info.json")) {
            throw "download archive does not contain convert_info.json."
        }

        $secondRefresh = Invoke-TfaCliJson -Arguments @("items", "refresh", "--json")
        if ([int]$secondRefresh.queued_count -ne 0 -or [int]$secondRefresh.skipped_count -lt 1) {
            throw "second refresh did not skip unchanged input: $($secondRefresh | ConvertTo-Json -Depth 12)"
        }
    }
    else {
        $refresh = Invoke-TfaCliJson -Arguments @("items", "refresh", "--queue-only", "--json")
        if ([string]$refresh.state -ne "pending") {
            throw "queue-only refresh did not create a pending run: $($refresh | ConvertTo-Json -Depth 12)"
        }
        if ([int]$refresh.queued_count -ne 1) {
            throw "queue-only refresh did not queue exactly one file: $($refresh | ConvertTo-Json -Depth 12)"
        }

        $runs = Invoke-TfaCliJson -Arguments @("runs", "list", "--json")
        if (@($runs).Count -lt 1) {
            throw "runs list returned no pending run."
        }
    }

    Write-Host "Operational test passed."
}
finally {
    try {
        $docker = Get-Command docker -ErrorAction SilentlyContinue
        if ($docker) {
            $composeArguments = @("compose", "-p", $projectName, "-f", (Join-Path $repoRoot "docker-compose.yml"))
            if (Test-Path -LiteralPath $testPathsOverridePath) {
                $composeArguments += @("-f", $testPathsOverridePath)
            }
            $composeArguments += @("down", "--remove-orphans", "-v")
            & $docker.Source @composeArguments *> $null
        }
    }
    catch {
        # Cleanup is best-effort. The next run uses a unique Docker project name.
    }

    if ($null -eq $originalComposeProjectName) {
        Remove-Item Env:\COMPOSE_PROJECT_NAME -ErrorAction SilentlyContinue
    }
    else {
        $env:COMPOSE_PROJECT_NAME = $originalComposeProjectName
    }

    if ($null -eq $originalHostSettingsPath) {
        Remove-Item Env:\TIMELINE_FOR_AUDIO_HOST_SETTINGS_PATH -ErrorAction SilentlyContinue
    }
    else {
        $env:TIMELINE_FOR_AUDIO_HOST_SETTINGS_PATH = $originalHostSettingsPath
    }

    if ($null -eq $originalPathsOverridePath) {
        Remove-Item Env:\TIMELINE_FOR_AUDIO_PATHS_OVERRIDE_PATH -ErrorAction SilentlyContinue
    }
    else {
        $env:TIMELINE_FOR_AUDIO_PATHS_OVERRIDE_PATH = $originalPathsOverridePath
    }

    if (Test-Path -LiteralPath $preparePathsScript) {
        & $preparePathsScript -RepoRoot $repoRoot | Out-Null
    }

    if (-not $KeepOutput) {
        Remove-Item -LiteralPath $runRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
    else {
        Write-Host "Kept operational test output: $runRoot"
    }
}
