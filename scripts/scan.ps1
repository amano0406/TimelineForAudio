param(
    [string]$Config = "",
    [string]$Output = ""
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$settingsPath = if ($Config) { [System.IO.Path]::GetFullPath($Config) } else { Join-Path $root "settings.json" }
if (-not (Test-Path -LiteralPath $settingsPath)) {
    throw "settings.json was not found: $settingsPath"
}

$settings = Get-Content -LiteralPath $settingsPath -Raw -Encoding UTF8 | ConvertFrom-Json
$runtime = if ($settings.PSObject.Properties["runtime"] -and $null -ne $settings.runtime) { $settings.runtime } else { [pscustomobject]@{} }
$apiPort = 19100
if ($runtime.PSObject.Properties["apiPort"]) {
    [void][int]::TryParse(([string]$runtime.apiPort), [ref]$apiPort)
}
if ($apiPort -lt 1 -or $apiPort -gt 65535) {
    $apiPort = 19100
}

if ($Output) {
    throw "-Output is not supported by the local API refresh endpoint. Set outputRoot in settings.json before running the scan."
}

$body = @{}
$json = $body | ConvertTo-Json -Depth 10 -Compress
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:$apiPort/items/refresh" -Body $json -ContentType "application/json" |
    ConvertTo-Json -Depth 50
