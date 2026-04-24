param()

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$webProject = Join-Path $repoRoot "web\TimelineForAudio.Web.csproj"
$project = Join-Path $repoRoot "tests\TimelineForAudio.E2E\TimelineForAudio.E2E.csproj"

function Resolve-DotnetCommand {
    $dotnetCommand = Get-Command dotnet -ErrorAction SilentlyContinue
    if ($dotnetCommand) {
        return $dotnetCommand.Source
    }

    $programFilesPath = Join-Path ${env:ProgramFiles} "dotnet\dotnet.exe"
    if (Test-Path $programFilesPath) {
        return $programFilesPath
    }

    throw "dotnet command was not found. Install .NET SDK or add dotnet.exe to PATH."
}

function Resolve-PowerShellCommand {
    $commands = @("powershell.exe", "pwsh.exe")
    foreach ($commandName in $commands) {
        $command = Get-Command $commandName -ErrorAction SilentlyContinue
        if ($command) {
            return $command.Source
        }
    }

    throw "PowerShell executable was not found. Install Windows PowerShell or PowerShell 7."
}

$dotnet = Resolve-DotnetCommand
$powerShell = Resolve-PowerShellCommand

& $dotnet build $webProject
& $dotnet build $project

$playwrightScript = Join-Path $repoRoot "tests\TimelineForAudio.E2E\bin\Debug\net10.0\playwright.ps1"
if (-not (Test-Path $playwrightScript)) {
    throw "Playwright install script not found at $playwrightScript"
}

& $powerShell -ExecutionPolicy Bypass -File $playwrightScript install chromium

try {
    & $dotnet test $project --no-build
}
catch {
    $message = $_.Exception.Message
    if ($message -match "0x800711C7" -or $message -match "application control policy") {
        throw "E2E test assembly load was blocked by Windows application control policy (0x800711C7). The app build completed, but the host machine prevented test execution."
    }

    throw
}
