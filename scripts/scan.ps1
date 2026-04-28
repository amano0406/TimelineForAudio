param(
    [string]$Config = "",
    [string]$Output = ""
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$tfa = Join-Path $root "tfa.ps1"
$arguments = @("scan")
if ($Config) {
    $arguments += @("--config", $Config)
}
if ($Output) {
    $arguments += @("--output", $Output)
}

& $tfa @arguments
