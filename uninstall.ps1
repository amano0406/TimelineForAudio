[CmdletBinding()]
param(
    [switch]$Yes,
    [switch]$KeepAppData,
    [switch]$KeepSettings,
    [switch]$KeepEnv
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
$volumes = @(
    "${composeProject}_uploads",
    "${composeProject}_outputs",
    "${composeProject}_hf-cache",
    "${composeProject}_torch-cache"
)

Write-Host ""
Write-Host "TimelineForAudio uninstall"
Write-Host ""
Write-Host "This will remove Docker containers, local images, project volumes, and the project network."
Write-Host "Optional cleanup can also remove saved app data, local settings, and local .env."
if (-not $KeepAppData) {
    Write-Host "Optional: saved app data volume: $appDataVolume"
}
if (-not $KeepSettings -and (Test-Path -LiteralPath (Join-Path $repoRoot "settings.json"))) {
    Write-Host "Optional: local settings.json."
}
if (-not $KeepEnv -and (Test-Path -LiteralPath (Join-Path $repoRoot ".env"))) {
    Write-Host "Optional: local .env."
}
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

foreach ($volume in $volumes) {
    Remove-TfaVolumeIfExists -VolumeName $volume
}

if (-not $KeepAppData) {
    Write-Host ""
    Write-Host "Saved app data volume:"
    Write-Host "  $appDataVolume"
    Write-Host "This includes saved token data and worker state."
    if (Confirm-TfaAction "Delete saved app data too? (y/n)") {
        Remove-TfaVolumeIfExists -VolumeName $appDataVolume
    }
    else {
        Write-Host "Kept saved app data volume: $appDataVolume"
    }
}
else {
    Write-Host "Kept saved app data volume: $appDataVolume"
}

$settingsPath = Join-Path $repoRoot "settings.json"
if (-not $KeepSettings -and (Test-Path -LiteralPath $settingsPath)) {
    Write-Host ""
    Write-Host "Local settings file:"
    Write-Host "  $settingsPath"
    Write-Host "This includes input and output directory settings."
    if (Confirm-TfaAction "Delete settings.json too? (y/n)") {
        Remove-Item -LiteralPath $settingsPath -Force
        Write-Host "Deleted settings.json"
    }
    else {
        Write-Host "Kept settings.json"
    }
}
elseif ($KeepSettings -and (Test-Path -LiteralPath $settingsPath)) {
    Write-Host "Kept settings.json"
}

$envPath = Join-Path $repoRoot ".env"
if (-not $KeepEnv -and (Test-Path -LiteralPath $envPath)) {
    Write-Host ""
    if (Confirm-TfaAction "Delete local .env too? (y/n)") {
        Remove-Item -LiteralPath $envPath -Force
        Write-Host "Deleted .env"
    }
    else {
        Write-Host "Kept .env"
    }
}

Write-Host ""
Write-Host "Uninstall completed."
exit 0
