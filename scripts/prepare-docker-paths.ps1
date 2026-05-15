[CmdletBinding()]
param(
    [string]$RepoRoot = "",
    [string]$SettingsPath = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $RepoRoot) {
    $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}
else {
    $RepoRoot = (Resolve-Path $RepoRoot).Path
}

function Convert-ToYamlSingleQuoted {
    param([string]$Value)
    return "'" + $Value.Replace("'", "''") + "'"
}

function Resolve-ExistingPath {
    param([string]$PathValue)

    if (-not $PathValue) {
        return $null
    }
    if (-not (Test-Path -LiteralPath $PathValue)) {
        return $null
    }
    return (Resolve-Path -LiteralPath $PathValue).Path
}

function Add-Mount {
    param(
        [System.Collections.Generic.List[object]]$Mappings,
        [System.Collections.Generic.List[string]]$VolumeLines,
        [string]$HostPath,
        [string]$ContainerPath,
        [bool]$ReadOnly,
        [bool]$CreateIfMissing
    )

    $trimmed = $HostPath.Trim()
    if (-not $trimmed) {
        return
    }

    if ($CreateIfMissing -and -not (Test-Path -LiteralPath $trimmed)) {
        New-Item -ItemType Directory -Path $trimmed | Out-Null
    }

    $resolved = Resolve-ExistingPath -PathValue $trimmed
    if (-not $resolved) {
        Write-Warning "Docker path mount skipped because the host path does not exist: $trimmed"
        return
    }

    $Mappings.Add([ordered]@{
        host = $resolved
        container = $ContainerPath
    }) | Out-Null

    $VolumeLines.Add("      - type: bind") | Out-Null
    $VolumeLines.Add("        source: $(Convert-ToYamlSingleQuoted -Value $resolved)") | Out-Null
    $VolumeLines.Add("        target: $ContainerPath") | Out-Null
    if ($ReadOnly) {
        $VolumeLines.Add("        read_only: true") | Out-Null
    }
}

$repoSettingsPath = Join-Path $RepoRoot "settings.json"
$settingsExamplePath = Join-Path $RepoRoot "settings.example.json"
$settingsOverridePath = [string]$SettingsPath
if (-not $settingsOverridePath -and $env:TIMELINE_FOR_AUDIO_HOST_SETTINGS_PATH) {
    $settingsOverridePath = [string]$env:TIMELINE_FOR_AUDIO_HOST_SETTINGS_PATH
}

$usingSettingsOverride = -not [string]::IsNullOrWhiteSpace($settingsOverridePath)
$sourceSettingsPath = if ($usingSettingsOverride) {
    $settingsOverridePath
}
elseif (Test-Path -LiteralPath $repoSettingsPath) {
    $repoSettingsPath
}
else {
    $settingsExamplePath
}
if (-not (Test-Path -LiteralPath $sourceSettingsPath)) {
    throw "settings file was not found: $sourceSettingsPath"
}
$sourceSettingsPath = (Resolve-Path -LiteralPath $sourceSettingsPath).Path

$settings = Get-Content -LiteralPath $sourceSettingsPath -Raw | ConvertFrom-Json
$mappings = [System.Collections.Generic.List[object]]::new()
$volumeLines = [System.Collections.Generic.List[string]]::new()
$apiVolumeLines = [System.Collections.Generic.List[string]]::new()

if ($usingSettingsOverride) {
    $VolumeLines.Add("      - type: bind") | Out-Null
    $VolumeLines.Add("        source: $(Convert-ToYamlSingleQuoted -Value $sourceSettingsPath)") | Out-Null
    $VolumeLines.Add("        target: /host/settings/settings.json") | Out-Null
    $VolumeLines.Add("        read_only: true") | Out-Null
    $apiVolumeLines.Add("      - type: bind") | Out-Null
    $apiVolumeLines.Add("        source: $(Convert-ToYamlSingleQuoted -Value $sourceSettingsPath)") | Out-Null
    $apiVolumeLines.Add("        target: /host/settings/settings.json") | Out-Null
    $apiVolumeLines.Add("        read_only: true") | Out-Null
}

$inputIndex = 0
foreach ($root in @($settings.inputRoots)) {
    if ($null -eq $root) {
        continue
    }
    $inputIndex += 1
    if ($root -isnot [string]) {
        throw "settings.inputRoots must be an array of path strings."
    }
    $rootPath = [string]$root
    $id = "input-$inputIndex"
    Add-Mount `
        -Mappings $mappings `
        -VolumeLines $volumeLines `
        -HostPath $rootPath `
        -ContainerPath "/host/input/$id" `
        -ReadOnly $true `
        -CreateIfMissing $false
}

$outputRoot = $settings.outputRoot
if ($null -ne $outputRoot) {
    if ($outputRoot -isnot [string]) {
        throw "settings.outputRoot must be a path string."
    }
    $outputRootPath = [string]$outputRoot
    Add-Mount `
        -Mappings $mappings `
        -VolumeLines $volumeLines `
        -HostPath $outputRootPath `
        -ContainerPath "/host/output/master" `
        -ReadOnly $false `
        -CreateIfMissing $true
}

$mappingRows = @()
foreach ($mapping in $mappings) {
    $mappingRows += $mapping
}
$json = ConvertTo-Json -InputObject $mappingRows -Compress
$lines = [System.Collections.Generic.List[string]]::new()
$lines.Add("services:") | Out-Null
$lines.Add("  worker:") | Out-Null
$lines.Add("    environment:") | Out-Null
$lines.Add("      TIMELINE_FOR_AUDIO_PATH_MAPPINGS: $(Convert-ToYamlSingleQuoted -Value $json)") | Out-Null
if ($usingSettingsOverride) {
    $lines.Add("      TIMELINE_FOR_AUDIO_SETTINGS_PATH: /host/settings/settings.json") | Out-Null
}
if ($volumeLines.Count -gt 0) {
    $lines.Add("    volumes:") | Out-Null
    foreach ($line in $volumeLines) {
        $lines.Add($line) | Out-Null
    }
}
if ($usingSettingsOverride) {
    $lines.Add("  api:") | Out-Null
    $lines.Add("    environment:") | Out-Null
    $lines.Add("      TIMELINE_FOR_AUDIO_SETTINGS_PATH: /host/settings/settings.json") | Out-Null
    if ($apiVolumeLines.Count -gt 0) {
        $lines.Add("    volumes:") | Out-Null
        foreach ($line in $apiVolumeLines) {
            $lines.Add($line) | Out-Null
        }
    }
}

$overridePath = [string]$env:TIMELINE_FOR_AUDIO_PATHS_OVERRIDE_PATH
if ($overridePath) {
    $overridePath = [System.IO.Path]::GetFullPath($overridePath)
    $generatedDir = Split-Path -Parent $overridePath
}
else {
    $generatedDir = Join-Path $RepoRoot ".docker"
    $overridePath = Join-Path $generatedDir "docker-compose.paths.yml"
}
New-Item -ItemType Directory -Path $generatedDir -Force | Out-Null
$lockPath = "$overridePath.lock"
$tempPath = Join-Path $generatedDir ("docker-compose.paths.{0}.tmp" -f ([guid]::NewGuid().ToString("N")))
$newContent = [string]::Join([Environment]::NewLine, $lines.ToArray()) + [Environment]::NewLine
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)

$lockStream = $null
for ($attempt = 1; $attempt -le 50; $attempt += 1) {
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
    throw "Timed out waiting for Docker path override lock: $lockPath"
}

try {
    if ((Test-Path -LiteralPath $overridePath) -and ((Get-Content -LiteralPath $overridePath -Raw) -eq $newContent)) {
        Write-Output $overridePath
        return
    }

    [System.IO.File]::WriteAllText($tempPath, $newContent, $utf8NoBom)
    Move-Item -LiteralPath $tempPath -Destination $overridePath -Force
}
finally {
    if ($lockStream) {
        $lockStream.Dispose()
    }
    if (Test-Path -LiteralPath $tempPath) {
        Remove-Item -LiteralPath $tempPath -Force
    }
}
Write-Output $overridePath
