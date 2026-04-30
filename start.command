#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"

run_compose_locked() {
  mkdir -p .docker
  if command -v flock >/dev/null 2>&1; then
    flock .docker/docker-compose.lock docker compose "$@"
  else
    docker compose "$@"
  fi
}

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker Desktop is not installed or docker is not on PATH."
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "Docker Desktop is installed but the Docker engine is not ready."
  echo "Start Docker Desktop and wait until the engine is running, then try again."
  exit 1
fi

if command -v pwsh >/dev/null 2>&1; then
  ps_cmd=(pwsh -NoLogo -NoProfile)
elif command -v powershell >/dev/null 2>&1; then
  ps_cmd=(powershell -NoLogo -NoProfile)
else
  echo "PowerShell was not found; cannot generate Docker host path mounts from Windows settings."
  echo "Start through PowerShell on Windows, or install pwsh for this WSL/Unix backdoor."
  exit 1
fi

path_compose_args=()
"${ps_cmd[@]}" -File "./scripts/prepare-docker-paths.ps1" -RepoRoot "$(pwd)" >/dev/null
path_compose_args=(-f .docker/docker-compose.paths.yml)

compute_mode=$("${ps_cmd[@]}" -Command '$p = Join-Path (Get-Location) "settings.json"; if (-not (Test-Path -LiteralPath $p)) { $p = Join-Path (Get-Location) "settings.example.json" }; $m = "cpu"; if (Test-Path -LiteralPath $p) { try { $s = Get-Content -LiteralPath $p -Raw | ConvertFrom-Json; if ($s.PSObject.Properties.Name -contains "computeMode") { $m = [string]$s.computeMode } } catch { $m = "cpu" } }; $m = $m.Trim().ToLowerInvariant(); if ($m -notin @("cpu", "gpu")) { $m = "cpu" }; Write-Output $m' | tr -d '\r')

compose_args=(-f docker-compose.yml)
compose_args+=("${path_compose_args[@]}")
if [[ "${compute_mode}" == "gpu" ]]; then
  if ! command -v nvidia-smi >/dev/null 2>&1 || ! nvidia-smi --query-gpu=name --format=csv,noheader >/dev/null 2>&1; then
    echo "settings.json computeMode is gpu, but NVIDIA GPU is not available from this shell."
    echo "Set computeMode to cpu or fix NVIDIA/Docker GPU support."
    exit 1
  fi
  compose_args+=(-f docker-compose.gpu.yml)
  echo "Compute mode: gpu"
  echo "Starting GPU worker image."
else
  echo "Compute mode: cpu"
fi

echo "Starting the worker container..."
run_compose_locked "${compose_args[@]}" up -d --remove-orphans worker

echo
echo "TimelineForAudio worker is running."
echo
echo "CLI examples:"
echo "  ./cli.command settings init"
echo "  ./cli.command settings status"
echo "  ./cli.command refresh"
echo "  ./cli.command runs list"
echo
echo "Docker status:"
docker compose "${compose_args[@]}" ps
