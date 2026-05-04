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
    throw "This smoke test must be run from Windows PowerShell because it verifies local cli.ps1 execution."
}

$cliPath = Join-Path $repoRoot "cli.ps1"
if (-not (Test-Path -LiteralPath $cliPath)) {
    throw "cli.ps1 was not found: $cliPath"
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

Write-Host "Running local cli.ps1 download smoke test..."
$result = Invoke-TfaPowerShellFile -FilePath $cliPath -Arguments @("items", "download", "--json")
$exitCode = $result.ExitCode
$rawOutput = [string]$result.Stdout
if ($exitCode -ne 0) {
    Write-Host $rawOutput
    Write-Host $result.Stderr
    throw "cli.ps1 items download failed with exit code $exitCode."
}

$payload = $null
try {
    $payload = ConvertFrom-TfaJsonPayload -Text $rawOutput
}
catch {
    Write-Host $rawOutput
    throw "cli.ps1 items download did not return a JSON payload."
}

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

Write-Host "Running local cli.ps1 explicit --output download smoke test..."
$explicitOutputDir = Join-Path $repoRoot "output\local-cli-download-smoke"
$explicitOutputPath = Join-Path $explicitOutputDir "requested-items.zip"
if (Test-Path -LiteralPath $explicitOutputPath) {
    Remove-Item -LiteralPath $explicitOutputPath -Force
}
$explicitResult = Invoke-TfaPowerShellFile -FilePath $cliPath -Arguments @("items", "download", "--output", $explicitOutputPath, "--json")
if ($explicitResult.ExitCode -ne 0) {
    Write-Host $explicitResult.Stdout
    Write-Host $explicitResult.Stderr
    throw "cli.ps1 items download --output failed with exit code $($explicitResult.ExitCode)."
}
$explicitPayload = ConvertFrom-TfaJsonPayload -Text ([string]$explicitResult.Stdout)
$explicitArchivePath = [string]$explicitPayload.archive_path
$expectedArchivePath = [System.IO.Path]::GetFullPath($explicitOutputPath)
if (-not ([System.String]::Equals($explicitArchivePath, $expectedArchivePath, [System.StringComparison]::OrdinalIgnoreCase))) {
    throw "cli.ps1 items download --output returned the wrong archive_path. Expected $expectedArchivePath but got $explicitArchivePath"
}
if (-not (Test-Path -LiteralPath $expectedArchivePath)) {
    throw "cli.ps1 items download --output did not create the requested host archive: $expectedArchivePath"
}
$explicitArchive = Get-Item -LiteralPath $expectedArchivePath
if ($explicitArchive.Length -le 0) {
    throw "Explicit output archive is empty: $expectedArchivePath"
}
Write-Host "Local cli.ps1 explicit --output download smoke test passed."
Write-Host "  Archive: $expectedArchivePath"
if (-not $KeepOutput) {
    Remove-Item -LiteralPath $expectedArchivePath -Force
    if (Test-Path -LiteralPath $explicitOutputDir) {
        Remove-Item -LiteralPath $explicitOutputDir -Recurse -Force
    }
    Write-Host "  Cleanup: removed explicit output archive"
}

Write-Host "Running local cli.ps1 JSON error smoke test..."
$errorResult = Invoke-TfaPowerShellFile -FilePath $cliPath -Arguments @("items", "download", "--item-id", "item-does-not-exist", "--json")
if ($errorResult.ExitCode -eq 0) {
    throw "cli.ps1 invalid items download unexpectedly succeeded."
}
if (-not [string]::IsNullOrWhiteSpace([string]$errorResult.Stderr)) {
    Write-Host $errorResult.Stderr
    throw "cli.ps1 JSON error wrote to stderr."
}
$errorPayload = ConvertFrom-TfaJsonPayload -Text ([string]$errorResult.Stdout)
if ($true -eq $errorPayload.ok) {
    throw "cli.ps1 JSON error payload did not report ok=false."
}
if ([string]$errorPayload.error.message -notmatch "Item not found") {
    throw "cli.ps1 JSON error payload did not include the expected message."
}
Write-Host "Local cli.ps1 JSON error smoke test passed."
