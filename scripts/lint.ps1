param(
    [Parameter()]
    [switch] $IncludeLocalCliDownload,

    [Parameter()]
    [switch] $IncludeOperationalSmoke
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

function Invoke-CheckedCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string] $FilePath,
        [Parameter(ValueFromRemainingArguments = $true)]
        [string[]] $Arguments
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed: $FilePath $($Arguments -join ' ')"
    }
}

function Resolve-Python {
    $windowsVenv = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path $windowsVenv) {
        return $windowsVenv
    }

    $unixVenv = Join-Path $repoRoot ".venv/bin/python"
    if (Test-Path $unixVenv) {
        return $unixVenv
    }

    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        return $pythonCommand.Source
    }

    throw "Python was not found. Create .venv or install Python before linting."
}

$python = Resolve-Python

$ruffAvailable = $false
$previousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $python -m ruff --version > $null 2>&1
$ruffExitCode = $LASTEXITCODE
$ErrorActionPreference = $previousErrorActionPreference
if ($ruffExitCode -eq 0) {
    $ruffAvailable = $true
}

if ($ruffAvailable) {
    Write-Host "Running Python lint..."
    Invoke-CheckedCommand $python -m ruff check worker/src worker/tests
    Invoke-CheckedCommand $python -m ruff format --check worker/src worker/tests
}
else {
    Write-Host "ruff is not installed; skipping ruff checks."
}

Write-Host "Running Python syntax check..."
Invoke-CheckedCommand $python -m compileall -q worker/src worker/tests

Write-Host "Running Python tests..."
$env:PYTHONPATH = "worker/src"
Invoke-CheckedCommand $python -m unittest discover -s worker/tests -p "test_*.py"

if ($IncludeLocalCliDownload) {
    & (Join-Path $repoRoot "scripts\test-local-cli-download.ps1")
    if ($LASTEXITCODE -ne 0) {
        throw "Local cli.ps1 download smoke test failed."
    }
}

if ($IncludeOperationalSmoke) {
    Write-Host "Running isolated operational smoke test..."
    & (Join-Path $repoRoot "scripts\test-operational.ps1")
    if (-not $?) {
        throw "Operational smoke test failed."
    }
}
