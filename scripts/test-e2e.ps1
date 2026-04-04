param()

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$webProject = Join-Path $repoRoot "web\Audio2Timeline.Web.csproj"
$project = Join-Path $repoRoot "tests\Audio2Timeline.E2E\Audio2Timeline.E2E.csproj"

dotnet build $webProject
dotnet build $project

$playwrightScript = Join-Path $repoRoot "tests\Audio2Timeline.E2E\bin\Debug\net10.0\playwright.ps1"
if (-not (Test-Path $playwrightScript)) {
    throw "Playwright install script not found at $playwrightScript"
}

powershell -ExecutionPolicy Bypass -File $playwrightScript install chromium
dotnet test $project --no-build
