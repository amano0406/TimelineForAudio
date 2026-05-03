[CmdletBinding()]
param(
    [Parameter()]
    [switch]$KeepOutput
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

function Convert-TfaContainerPathToHostPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PathText
    )

    $normalized = $PathText.Replace("\", "/")
    if ($normalized -eq "/workspace") {
        return $repoRoot
    }
    if ($normalized.StartsWith("/workspace/")) {
        $relativePath = $normalized.Substring("/workspace/".Length).Replace("/", [System.IO.Path]::DirectorySeparatorChar)
        return Join-Path $repoRoot $relativePath
    }
    return $PathText
}

if ([System.IO.Path]::DirectorySeparatorChar -ne "\") {
    throw "This smoke test must be run from Windows PowerShell because it verifies local cli.ps1 execution."
}

$cliPath = Join-Path $repoRoot "cli.ps1"
if (-not (Test-Path -LiteralPath $cliPath)) {
    throw "cli.ps1 was not found: $cliPath"
}

Write-Host "Running local cli.ps1 download smoke test..."
$commandOutput = & $cliPath items download --json 2>&1
$exitCode = $LASTEXITCODE
$rawOutput = ($commandOutput | ForEach-Object { $_.ToString() }) -join "`n"
if ($exitCode -ne 0) {
    Write-Host $rawOutput
    throw "cli.ps1 items download failed with exit code $exitCode."
}

$jsonStart = $rawOutput.IndexOf("{")
$jsonEnd = $rawOutput.LastIndexOf("}")
if ($jsonStart -lt 0 -or $jsonEnd -lt $jsonStart) {
    Write-Host $rawOutput
    throw "cli.ps1 items download did not return a JSON payload."
}

$payload = $rawOutput.Substring($jsonStart, $jsonEnd - $jsonStart + 1) | ConvertFrom-Json
$itemIds = @($payload.item_ids)
if ($itemIds.Count -le 0) {
    throw "cli.ps1 items download returned no item ids."
}

$archivePathText = [string]$payload.archive_path
if ([string]::IsNullOrWhiteSpace($archivePathText)) {
    throw "cli.ps1 items download did not return archive_path."
}

$hostArchivePath = Convert-TfaContainerPathToHostPath -PathText $archivePathText
if (-not (Test-Path -LiteralPath $hostArchivePath)) {
    throw "Download archive was not found on the host: $hostArchivePath"
}

$archive = Get-Item -LiteralPath $hostArchivePath
if ($archive.Length -le 0) {
    throw "Download archive is empty: $hostArchivePath"
}

Write-Host "Local cli.ps1 download smoke test passed."
Write-Host "  Items:   $($itemIds.Count)"
Write-Host "  Archive: $hostArchivePath"

if (-not $KeepOutput) {
    Remove-Item -LiteralPath $hostArchivePath -Force
    Write-Host "  Cleanup: removed generated archive"
}
