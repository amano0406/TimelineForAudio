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

if [[ ! -f ".env" ]]; then
  cp ".env.example" ".env"
  echo "Created .env from .env.example."
fi

path_compose_args=()
if command -v pwsh >/dev/null 2>&1; then
  pwsh -NoLogo -NoProfile -File "./scripts/prepare-docker-paths.ps1" -RepoRoot "$(pwd)" >/dev/null
  path_compose_args=(-f .docker/docker-compose.paths.yml)
elif command -v powershell >/dev/null 2>&1; then
  powershell -NoLogo -NoProfile -File "./scripts/prepare-docker-paths.ps1" -RepoRoot "$(pwd)" >/dev/null
  path_compose_args=(-f .docker/docker-compose.paths.yml)
else
  echo "PowerShell was not found; Docker will run without generated host path mounts."
fi

compose_args=(-f docker-compose.yml)
compose_args+=("${path_compose_args[@]}")
if command -v nvidia-smi >/dev/null 2>&1; then
  compose_args+=(-f docker-compose.gpu.yml)
  echo "NVIDIA GPU detected. Starting GPU worker image."
fi

echo "Starting the worker container..."
run_compose_locked "${compose_args[@]}" up -d --remove-orphans worker

echo
echo "TimelineForAudio worker is running."
echo
echo "CLI examples:"
echo "  ./tfa.command settings init"
echo "  ./tfa.command settings status"
echo "  ./tfa.command refresh --ipa-only"
echo "  ./tfa.command jobs list"
echo
echo "Docker status:"
docker compose "${compose_args[@]}" ps
