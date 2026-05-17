[CmdletBinding()]
param(
    [Parameter()]
    [switch]$UseRealModels,

    [Parameter()]
    [switch]$KeepOutput,

    [Parameter()]
    [string]$SourceAudioPath = "",

    [Parameter()]
    [long]$MaxSourceAudioBytes = 52428800,

    [Parameter()]
    [string]$WorkRoot = "C:\Codex\workspaces\TimelineForAudio\operational-tests"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot

function Get-TfaApiBaseUrl {
    $manifestPath = Join-Path $repoRoot "timeline-product.json"
    if (Test-Path -LiteralPath $manifestPath -PathType Leaf) {
        try {
            $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($manifest.api.defaultBaseUrl) {
                return ([string]$manifest.api.defaultBaseUrl).TrimEnd("/")
            }
            if ($manifest.api.defaultPort) {
                return "http://127.0.0.1:$([int]$manifest.api.defaultPort)"
            }
        }
        catch {
        }
    }
    return "http://127.0.0.1:19100"
}

function Invoke-TfaApi {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [object]$Body = @{},
        [int]$TimeoutSeconds = 60
    )

    $json = $Body | ConvertTo-Json -Depth 20 -Compress
    return Invoke-RestMethod `
        -UseBasicParsing `
        -TimeoutSec $TimeoutSeconds `
        -Uri "$script:ApiBaseUrl/$Path" `
        -Method Post `
        -ContentType "application/json" `
        -Body $json
}

function Assert-Tfa {
    param(
        [Parameter(Mandatory = $true)][bool]$Condition,
        [Parameter(Mandatory = $true)][string]$Message
    )
    if (-not $Condition) {
        throw $Message
    }
}

$script:ApiBaseUrl = Get-TfaApiBaseUrl
Write-Host "TimelineForAudio API operational smoke: $script:ApiBaseUrl"

$health = Invoke-WebRequest -UseBasicParsing -TimeoutSec 10 -Uri "$script:ApiBaseUrl/health"
Assert-Tfa ($health.StatusCode -ge 200 -and $health.StatusCode -lt 300) "Health endpoint returned HTTP $($health.StatusCode)."
Assert-Tfa (([string]$health.Content).Trim() -ne "false") "Health endpoint returned false."

$settings = Invoke-TfaApi -Path "settings/status"
Assert-Tfa ($null -ne $settings) "settings/status returned no payload."

$files = Invoke-TfaApi -Path "files/list" -Body @{ page = 1; pageSize = 1 }
Assert-Tfa ($null -ne $files) "files/list returned no payload."

$items = Invoke-TfaApi -Path "items/list" -Body @{ page = 1; pageSize = 1 }
Assert-Tfa ($null -ne $items) "items/list returned no payload."

if ($UseRealModels) {
    $refreshBody = @{ maxItems = 1 }
    if ($SourceAudioPath) {
        Write-Warning "SourceAudioPath is no longer used by this API smoke. Configure input roots in settings.json."
    }
    if ($MaxSourceAudioBytes -ne 52428800) {
        Write-Warning "MaxSourceAudioBytes is no longer used by this API smoke."
    }
    $refresh = Invoke-TfaApi -Path "items/refresh" -Body $refreshBody -TimeoutSeconds 900
    Assert-Tfa ($null -ne $refresh) "items/refresh returned no payload."
}

if ($KeepOutput) {
    Write-Host "KeepOutput is accepted for compatibility; this API smoke does not create an isolated output directory."
}
if ($WorkRoot) {
    Write-Host "WorkRoot is accepted for compatibility; this API smoke uses the configured product settings."
}

Write-Host "TimelineForAudio API operational smoke passed."
