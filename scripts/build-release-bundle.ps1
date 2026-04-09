[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Version,

    [Parameter()]
    [string]$OutputDir = ".\\release",

    [Parameter()]
    [switch]$KeepStaging
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Normalize-Version {
    param([string]$Value)

    $trimmed = $Value.Trim()
    if ($trimmed.StartsWith("v")) {
        $trimmed = $trimmed.Substring(1)
    }

    if ($trimmed -notmatch '^\d+\.\d+\.\d+$') {
        throw "Version must look like 0.3.0 or v0.3.0."
    }

    return @{
        SemVer = $trimmed
        Tag = "v$trimmed"
    }
}

function Test-IsExcludedPath {
    param([string]$RelativePath)

    $normalized = $RelativePath.Replace('\', '/')
    $excludedSegments = @(
        ".git",
        ".ruff_cache",
        "__pycache__",
        ".pytest_cache",
        "node_modules",
        "bin",
        "obj"
    )

    foreach ($segment in $excludedSegments) {
        if ($normalized -match "(^|/)$([Regex]::Escape($segment))(/|$)") {
            return $true
        }
    }

    return $false
}

function Get-RepoRelativePath {
    param(
        [string]$RepoRoot,
        [string]$FullPath
    )

    $normalizedRoot = $RepoRoot.TrimEnd('\', '/')
    $rootWithSeparator = $normalizedRoot + [System.IO.Path]::DirectorySeparatorChar
    if (-not $FullPath.StartsWith($rootWithSeparator, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Path is not under the repository root: $FullPath"
    }

    return $FullPath.Substring($rootWithSeparator.Length).Replace('\', '/')
}

function Copy-ReleaseFiles {
    param(
        [string]$RepoRoot,
        [string]$DestinationRoot
    )

    $exactFiles = @(
        ".dockerignore",
        ".env.example",
        "Directory.Build.props",
        "LICENSE",
        "MODEL_AND_RUNTIME_NOTES.md",
        "README.md",
        "README.ja.md",
        "THIRD_PARTY_NOTICES.md",
        "docker-compose.yml",
        "docker-compose.gpu.yml",
        "start.bat",
        "start.command",
        "stop.bat",
        "stop.command",
        "uninstall.bat",
        "uninstall.command",
        "worker/pyproject.toml",
        "worker/requirements-cpu.txt",
        "docs/PUBLIC_RELEASE_CHECKLIST.md",
        "docs/SECURITY_AND_SAFETY.md",
        "scripts/open-app-window.ps1"
    )

    $directories = @(
        "configs",
        "docker",
        "web",
        "worker/src",
        "docs/examples",
        "docs/screenshots"
    )

    foreach ($relativePath in $exactFiles) {
        $sourcePath = Join-Path $RepoRoot $relativePath
        if (-not (Test-Path -LiteralPath $sourcePath)) {
            continue
        }

        $destinationPath = Join-Path $DestinationRoot $relativePath
        $destinationDir = Split-Path -Parent $destinationPath
        if (-not (Test-Path -LiteralPath $destinationDir)) {
            New-Item -ItemType Directory -Path $destinationDir | Out-Null
        }
        Copy-Item -LiteralPath $sourcePath -Destination $destinationPath -Force
    }

    foreach ($relativeDirectory in $directories) {
        $sourceDirectory = Join-Path $RepoRoot $relativeDirectory
        if (-not (Test-Path -LiteralPath $sourceDirectory)) {
            continue
        }

        foreach ($file in Get-ChildItem -LiteralPath $sourceDirectory -Recurse -File) {
            $sourcePath = $file.FullName
            $relativePath = Get-RepoRelativePath -RepoRoot $RepoRoot -FullPath $sourcePath
            if (Test-IsExcludedPath -RelativePath $relativePath) {
                continue
            }

            $destinationPath = Join-Path $DestinationRoot $relativePath
            $destinationDir = Split-Path -Parent $destinationPath
            if (-not (Test-Path -LiteralPath $destinationDir)) {
                New-Item -ItemType Directory -Path $destinationDir | Out-Null
            }
            Copy-Item -LiteralPath $sourcePath -Destination $destinationPath -Force
        }
    }
}

$normalized = Normalize-Version -Value $Version
$semVer = $normalized.SemVer
$tag = $normalized.Tag

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = (Resolve-Path (Join-Path $scriptRoot "..")).Path
if ([System.IO.Path]::IsPathRooted($OutputDir)) {
    $outputRoot = [System.IO.Path]::GetFullPath($OutputDir)
}
else {
    $outputRoot = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $OutputDir))
}
$bundleRootName = "TimelineForAudio-$tag"
$bundleStageRoot = Join-Path $outputRoot "staging"
$bundleRoot = Join-Path $bundleStageRoot $bundleRootName
$zipPath = Join-Path $outputRoot "TimelineForAudio-windows-local.zip"
$checksumPath = Join-Path $outputRoot "SHA256SUMS.txt"

if (Test-Path -LiteralPath $bundleStageRoot) {
    Remove-Item -LiteralPath $bundleStageRoot -Recurse -Force
}
if (-not (Test-Path -LiteralPath $outputRoot)) {
    New-Item -ItemType Directory -Path $outputRoot | Out-Null
}
if (Test-Path -LiteralPath $zipPath) {
    Remove-Item -LiteralPath $zipPath -Force
}
if (Test-Path -LiteralPath $checksumPath) {
    Remove-Item -LiteralPath $checksumPath -Force
}

New-Item -ItemType Directory -Path $bundleRoot | Out-Null
Copy-ReleaseFiles -RepoRoot $repoRoot -DestinationRoot $bundleRoot

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zipStream = [System.IO.File]::Open($zipPath, [System.IO.FileMode]::Create)
try {
    $archive = New-Object System.IO.Compression.ZipArchive($zipStream, [System.IO.Compression.ZipArchiveMode]::Create, $false)
    try {
        $normalizedStageRoot = (Resolve-Path $bundleStageRoot).Path.TrimEnd('\', '/')
        foreach ($file in Get-ChildItem -LiteralPath $bundleStageRoot -Recurse -File) {
            $entryName = $file.FullName.Substring($normalizedStageRoot.Length + 1).Replace('\', '/')
            [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
                $archive,
                $file.FullName,
                $entryName,
                [System.IO.Compression.CompressionLevel]::Optimal) | Out-Null
        }
    }
    finally {
        $archive.Dispose()
    }
}
finally {
    $zipStream.Dispose()
}

$hash = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content -LiteralPath $checksumPath -Value "$hash  TimelineForAudio-windows-local.zip"

if (-not $KeepStaging -and (Test-Path -LiteralPath $bundleStageRoot)) {
    Remove-Item -LiteralPath $bundleStageRoot -Recurse -Force
}

Write-Host "Release bundle created:"
Write-Host "  Version: $semVer"
Write-Host "  Folder:  $bundleRootName"
Write-Host "  ZIP:     $zipPath"
Write-Host "  SHA256:  $checksumPath"
