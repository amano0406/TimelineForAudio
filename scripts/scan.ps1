param(
    [string]$Config = "",
    [string]$Output = ""
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$cli = Join-Path $root "cli.ps1"
$arguments = @("scan")
if ($Config) {
    $arguments += @("--config", $Config)
}
if ($Output) {
    $arguments += @("--output", $Output)
}

& $cli @arguments
