[CmdletBinding()]
param(
    [string]$RepoRoot = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $RepoRoot) {
    $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}
else {
    $RepoRoot = (Resolve-Path $RepoRoot).Path
}

function Convert-ToSafeSegment {
    param(
        [string]$Value,
        [string]$Fallback
    )

    $candidate = if ($Value) { $Value } else { $Fallback }
    $candidate = $candidate.ToLowerInvariant() -replace '[^a-z0-9_-]+', '-'
    $candidate = $candidate.Trim('-')
    if ($candidate) {
        return $candidate
    }
    return $Fallback
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

$settingsPath = Join-Path $RepoRoot "settings.json"
$settingsExamplePath = Join-Path $RepoRoot "settings.example.json"
$sourceSettingsPath = if (Test-Path -LiteralPath $settingsPath) { $settingsPath } else { $settingsExamplePath }
if (-not (Test-Path -LiteralPath $sourceSettingsPath)) {
    throw "settings.json or settings.example.json was not found."
}

$settings = Get-Content -LiteralPath $sourceSettingsPath -Raw | ConvertFrom-Json
$mappings = [System.Collections.Generic.List[object]]::new()
$volumeLines = [System.Collections.Generic.List[string]]::new()

$inputIndex = 0
foreach ($root in @($settings.inputRoots)) {
    if ($null -eq $root) {
        continue
    }
    if ($root.PSObject.Properties.Name -contains "enabled" -and -not [bool]$root.enabled) {
        continue
    }
    $inputIndex += 1
    $id = Convert-ToSafeSegment -Value ([string]$root.id) -Fallback "input-$inputIndex"
    Add-Mount `
        -Mappings $mappings `
        -VolumeLines $volumeLines `
        -HostPath ([string]$root.path) `
        -ContainerPath "/host/input/$id" `
        -ReadOnly $true `
        -CreateIfMissing $false
}

$outputIndex = 0
foreach ($root in @($settings.outputRoots)) {
    if ($null -eq $root) {
        continue
    }
    if ($root.PSObject.Properties.Name -contains "enabled" -and -not [bool]$root.enabled) {
        continue
    }
    $outputIndex += 1
    $id = Convert-ToSafeSegment -Value ([string]$root.id) -Fallback "output-$outputIndex"
    Add-Mount `
        -Mappings $mappings `
        -VolumeLines $volumeLines `
        -HostPath ([string]$root.path) `
        -ContainerPath "/host/output/$id" `
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
if ($volumeLines.Count -gt 0) {
    $lines.Add("    volumes:") | Out-Null
    foreach ($line in $volumeLines) {
        $lines.Add($line) | Out-Null
    }
}

$generatedDir = Join-Path $RepoRoot ".docker"
New-Item -ItemType Directory -Path $generatedDir -Force | Out-Null
$overridePath = Join-Path $generatedDir "docker-compose.paths.yml"
$lockPath = Join-Path $generatedDir "docker-compose.paths.lock"
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
