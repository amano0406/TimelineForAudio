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
  echo "Docker Desktop is not installed or docker is not on PATH." >&2
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "Docker Desktop is installed but the Docker engine is not ready." >&2
  echo "Start Docker Desktop and wait until the engine is running, then try again." >&2
  exit 1
fi

compose_args=(-f docker-compose.yml)
requires_configured_worker=false
case "${1:-}" in
  process-run|daemon)
    requires_configured_worker=true
    ;;
  files|items)
    requires_configured_worker=true
    ;;
esac

can_start_worker=true
ps_cmd=()
if command -v pwsh >/dev/null 2>&1; then
  ps_cmd=(pwsh -NoLogo -NoProfile)
  "${ps_cmd[@]}" -File "./scripts/prepare-docker-paths.ps1" -RepoRoot "$(pwd)" >/dev/null
  compose_args+=(-f .docker/docker-compose.paths.yml)
elif command -v powershell >/dev/null 2>&1; then
  ps_cmd=(powershell -NoLogo -NoProfile)
  "${ps_cmd[@]}" -File "./scripts/prepare-docker-paths.ps1" -RepoRoot "$(pwd)" >/dev/null
  compose_args+=(-f .docker/docker-compose.paths.yml)
else
  if [[ "${requires_configured_worker}" == "true" ]]; then
    echo "This command needs configured Docker host path mounts." >&2
    echo "Run it through cli.ps1 or cli.bat from Windows PowerShell so settings.json paths are mounted correctly." >&2
    exit 1
  fi
  echo "PowerShell was not found; cannot start or update Docker host path mounts from this WSL/Unix shell."
  echo "Trying to use an already-running worker. Use PowerShell on Windows for refresh or path changes."
  can_start_worker=false
fi

if [[ "${requires_configured_worker}" == "true" && "${#ps_cmd[@]}" -gt 0 ]]; then
  compute_mode=$("${ps_cmd[@]}" -Command '$p = Join-Path (Get-Location) "settings.json"; if (-not (Test-Path -LiteralPath $p)) { $p = Join-Path (Get-Location) "settings.example.json" }; $m = "cpu"; if (Test-Path -LiteralPath $p) { try { $s = Get-Content -LiteralPath $p -Raw | ConvertFrom-Json; if ($s.PSObject.Properties.Name -contains "computeMode") { $m = [string]$s.computeMode } } catch { $m = "cpu" } }; $m = $m.Trim().ToLowerInvariant(); if ($m -notin @("cpu", "gpu")) { $m = "cpu" }; Write-Output $m' | tr -d '\r')
  if [[ "${compute_mode}" == "gpu" ]]; then
    if ! command -v nvidia-smi >/dev/null 2>&1 || ! nvidia-smi --query-gpu=name --format=csv,noheader >/dev/null 2>&1; then
      echo "settings.json computeMode is gpu, but NVIDIA GPU is not available from this shell." >&2
      echo "Set computeMode to cpu or fix NVIDIA/Docker GPU support." >&2
      exit 1
    fi
    compose_args+=(-f docker-compose.gpu.yml)
  fi
fi

if [[ "${can_start_worker}" == "true" ]]; then
  if [[ "${requires_configured_worker}" == "true" ]]; then
    run_compose_locked "${compose_args[@]}" up -d --remove-orphans worker
  else
    run_compose_locked "${compose_args[@]}" up -d --no-recreate worker
  fi
fi
exec docker compose "${compose_args[@]}" exec -T worker python -m timeline_for_audio_worker "$@"
