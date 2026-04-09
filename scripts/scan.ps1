param(
    [string]$Config = "C:\apps\TimelineForAudio\configs\local.json",
    [string]$Output = "C:\apps\TimelineForAudio\runs\discovery.json"
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $root ".venv\Scripts\python.exe"
$python = if (Test-Path $venvPython) { $venvPython } else { "python" }

$env:PYTHONPATH = Join-Path $root "worker\src"

& $python -m timeline_for_audio_worker scan --config $Config --output $Output
