[CmdletBinding()]
param(
    [Parameter()]
    [switch]$KeepOutput
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Net.Http

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

    $allArguments = @(
        "-NoLogo",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        $FilePath
    ) + @($Arguments)

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

if ([System.IO.Path]::DirectorySeparatorChar -ne "\") {
    throw "This smoke test must be run from Windows PowerShell because it verifies local API access."
}

function ConvertFrom-TfaJsonPayload {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Text
    )

    $trimmed = $Text.Trim()
    $jsonStart = $trimmed.IndexOf("{")
    $jsonEnd = $trimmed.LastIndexOf("}")
    if ($jsonStart -lt 0 -or $jsonEnd -lt $jsonStart) {
        throw "Text did not contain a JSON object."
    }
    return $trimmed.Substring($jsonStart, $jsonEnd - $jsonStart + 1) | ConvertFrom-Json
}

function Get-TfaApiBaseUrl {
    $settingsPath = Join-Path $repoRoot "settings.json"
    $apiPort = 19100
    if (Test-Path -LiteralPath $settingsPath) {
        $settings = Get-Content -LiteralPath $settingsPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($settings.PSObject.Properties["runtime"] -and $settings.runtime.PSObject.Properties["apiPort"]) {
            [void][int]::TryParse(([string]$settings.runtime.apiPort), [ref]$apiPort)
        }
    }
    if ($apiPort -lt 1 -or $apiPort -gt 65535) {
        $apiPort = 19100
    }
    return "http://127.0.0.1:$apiPort"
}

function Invoke-TfaApi {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [hashtable]$Body = @{}
    )

    $client = [System.Net.Http.HttpClient]::new()
    try {
        $url = (Get-TfaApiBaseUrl).TrimEnd("/") + "/" + $Path.TrimStart("/")
        $json = $Body | ConvertTo-Json -Depth 20 -Compress
        $content = [System.Net.Http.StringContent]::new($json, [System.Text.Encoding]::UTF8, "application/json")
        $response = $client.PostAsync($url, $content).GetAwaiter().GetResult()
        $text = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        return [pscustomobject]@{
            ExitCode = if ($response.IsSuccessStatusCode) { 0 } else { [int]$response.StatusCode }
            Stdout = $text
            Stderr = ""
        }
    }
    finally {
        $client.Dispose()
    }
}

Write-Host "Running local API download smoke test..."
$result = Invoke-TfaApi -Path "items/download"
$exitCode = $result.ExitCode
$rawOutput = [string]$result.Stdout
if ($exitCode -ne 0) {
    Write-Host $rawOutput
    Write-Host $result.Stderr
    throw "API items download failed with status $exitCode."
}

$payload = $null
try {
    $payload = ConvertFrom-TfaJsonPayload -Text $rawOutput
}
catch {
    Write-Host $rawOutput
    throw "API items download did not return a JSON payload."
}

$itemIds = @($payload.item_ids)
if ($itemIds.Count -le 0) {
    throw "API items download returned no item ids."
}

$archivePathText = [string]$payload.archive_path
if ([string]::IsNullOrWhiteSpace($archivePathText)) {
    throw "API items download did not return archive_path."
}

$hostArchivePath = Convert-TfaContainerPathToHostPath -PathText $archivePathText
if (-not (Test-Path -LiteralPath $hostArchivePath)) {
    throw "Download archive was not found on the host: $hostArchivePath"
}

$archive = Get-Item -LiteralPath $hostArchivePath
if ($archive.Length -le 0) {
    throw "Download archive is empty: $hostArchivePath"
}

Write-Host "Local API download smoke test passed."
Write-Host "  Items:   $($itemIds.Count)"
Write-Host "  Archive: $hostArchivePath"

if (-not $KeepOutput) {
    Remove-Item -LiteralPath $hostArchivePath -Force
    Write-Host "  Cleanup: removed generated archive"
}

Write-Host "Running local API explicit output download smoke test..."
$explicitOutputDir = Join-Path $repoRoot "output\local-api-download-smoke"
$explicitOutputPath = Join-Path $explicitOutputDir "requested-items.zip"
if (Test-Path -LiteralPath $explicitOutputPath) {
    Remove-Item -LiteralPath $explicitOutputPath -Force
}
$explicitResult = Invoke-TfaApi -Path "items/download" -Body @{
    outputPath = $explicitOutputPath
}
if ($explicitResult.ExitCode -ne 0) {
    Write-Host $explicitResult.Stdout
    Write-Host $explicitResult.Stderr
    throw "API items download with outputPath failed with status $($explicitResult.ExitCode)."
}
$explicitPayload = ConvertFrom-TfaJsonPayload -Text ([string]$explicitResult.Stdout)
$explicitArchivePath = [string]$explicitPayload.archive_path
$expectedArchivePath = [System.IO.Path]::GetFullPath($explicitOutputPath)
if (-not ([System.String]::Equals($explicitArchivePath, $expectedArchivePath, [System.StringComparison]::OrdinalIgnoreCase))) {
    throw "API items download returned the wrong archive_path. Expected $expectedArchivePath but got $explicitArchivePath"
}
if (-not (Test-Path -LiteralPath $expectedArchivePath)) {
    throw "API items download did not create the requested host archive: $expectedArchivePath"
}
$explicitArchive = Get-Item -LiteralPath $expectedArchivePath
if ($explicitArchive.Length -le 0) {
    throw "Explicit output archive is empty: $expectedArchivePath"
}
Write-Host "Local API explicit output download smoke test passed."
Write-Host "  Archive: $expectedArchivePath"
if (-not $KeepOutput) {
    Remove-Item -LiteralPath $expectedArchivePath -Force
    if (Test-Path -LiteralPath $explicitOutputDir) {
        Remove-Item -LiteralPath $explicitOutputDir -Recurse -Force
    }
    Write-Host "  Cleanup: removed explicit output archive"
}

Write-Host "Running local API JSON error smoke test..."
$errorResult = Invoke-TfaApi -Path "items/download" -Body @{
    itemIds = @("item-does-not-exist")
}
if ($errorResult.ExitCode -eq 0) {
    throw "API invalid items download unexpectedly succeeded."
}
if (-not [string]::IsNullOrWhiteSpace([string]$errorResult.Stderr)) {
    Write-Host $errorResult.Stderr
    throw "API JSON error wrote to stderr."
}
$errorPayload = ConvertFrom-TfaJsonPayload -Text ([string]$errorResult.Stdout)
if ($true -eq $errorPayload.ok) {
    throw "API JSON error payload did not report ok=false."
}
if ([string]$errorPayload.error.message -notmatch "Item not found") {
    throw "API JSON error payload did not include the expected message."
}
Write-Host "Local API JSON error smoke test passed."
