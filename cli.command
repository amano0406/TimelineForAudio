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
can_start_worker=true
if command -v pwsh >/dev/null 2>&1; then
  pwsh -NoLogo -NoProfile -File "./scripts/prepare-docker-paths.ps1" -RepoRoot "$(pwd)" >/dev/null
  compose_args+=(-f .docker/docker-compose.paths.yml)
elif command -v powershell >/dev/null 2>&1; then
  powershell -NoLogo -NoProfile -File "./scripts/prepare-docker-paths.ps1" -RepoRoot "$(pwd)" >/dev/null
  compose_args+=(-f .docker/docker-compose.paths.yml)
else
  echo "PowerShell was not found; cannot start or update Docker host path mounts from this WSL/Unix shell."
  echo "Trying to use an already-running worker. Use PowerShell on Windows for refresh or path changes."
  can_start_worker=false
fi

if command -v nvidia-smi >/dev/null 2>&1; then
  compose_args+=(-f docker-compose.gpu.yml)
fi

if [[ "${can_start_worker}" == "true" ]]; then
  run_compose_locked "${compose_args[@]}" up -d --remove-orphans worker
fi
exec docker compose "${compose_args[@]}" exec -T worker python -m timeline_for_audio_worker "$@"
