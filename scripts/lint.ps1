param()

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

Write-Host "Running Python lint..."
Invoke-CheckedCommand $python -m ruff check worker/src worker/tests
Invoke-CheckedCommand $python -m ruff format --check worker/src worker/tests
