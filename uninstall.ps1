[CmdletBinding()]
param(
    [switch]$Yes,
    [switch]$RemoveAppData,
    [switch]$RemoveCache,
    [switch]$RemoveSettings
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = $PSScriptRoot
. (Join-Path $repoRoot "scripts\docker-runtime.ps1")

function Confirm-TfaAction {
    param([Parameter(Mandatory = $true)][string]$Prompt)

    if ($Yes) {
        return $true
    }
    $answer = Read-Host $Prompt
    return $answer -match '^(y|yes)$'
}

function Remove-TfaVolumeIfExists {
    param([Parameter(Mandatory = $true)][string]$VolumeName)

    $volumeNames = @(& $docker volume ls --format "{{.Name}}")
    if ($volumeNames -notcontains $VolumeName) {
        return
    }
    & $docker volume rm $VolumeName > $null
    if ((Get-TfaLastExitCode) -ne 0) {
        throw "Failed to remove Docker volume: $VolumeName"
    }
    Write-Host "Removed Docker volume: $VolumeName"
}

Initialize-TfaDocker -RepoRoot $repoRoot
$docker = Get-TfaDockerCommand
$composeArgs = @("-f", (Join-Path $repoRoot "docker-compose.yml"))
$gpuCompose = Join-Path $repoRoot "docker-compose.gpu.yml"
if (Test-Path -LiteralPath $gpuCompose) {
    $composeArgs += @("-f", $gpuCompose)
}

$composeProject = "timeline-for-audio"
$appDataVolume = "${composeProject}_app-data"
$cacheVolume = "${composeProject}_cache-data"

Write-Host ""
Write-Host "TimelineForAudio uninstall"
Write-Host ""
Write-Host "This will remove Docker containers, local images, and the project network."
Write-Host "Persistent volumes and settings are kept by default."
Write-Host ""
Write-Host "Optional removal switches:"
Write-Host "  -RemoveAppData   remove run history, catalog cache, ETA history"
Write-Host "  -RemoveCache     remove downloaded model cache"
Write-Host "  -RemoveSettings  remove local settings.json"
Write-Host ""

if (-not (Confirm-TfaAction "Continue with uninstall? (y/n)")) {
    Write-Host "Uninstall canceled."
    exit 1
}

Set-Location $repoRoot
Write-Host "Stopping and removing Docker resources..."
& $docker compose @composeArgs down --rmi local --remove-orphans
if (-not $?) {
    throw "Docker cleanup failed."
}

if ($RemoveAppData) {
    Remove-TfaVolumeIfExists -VolumeName $appDataVolume
}
else {
    Write-Host "Kept Docker volume: $appDataVolume"
}

if ($RemoveCache) {
    Remove-TfaVolumeIfExists -VolumeName $cacheVolume
}
else {
    Write-Host "Kept Docker volume: $cacheVolume"
}

$settingsPath = Join-Path $repoRoot "settings.json"
if ($RemoveSettings -and (Test-Path -LiteralPath $settingsPath)) {
    Write-Host ""
    Write-Host "Local settings file:"
    Write-Host "  $settingsPath"
    Write-Host "This includes input/output directories and Hugging Face token."
    if ($Yes -or (Confirm-TfaAction "Delete settings.json? (y/n)")) {
        Remove-Item -LiteralPath $settingsPath -Force
        Write-Host "Deleted settings.json"
    }
    else {
        Write-Host "Kept settings.json"
    }
}
elseif (Test-Path -LiteralPath $settingsPath) {
    Write-Host "Kept settings.json"
}

Write-Host ""
Write-Host "Uninstall completed."
exit 0
