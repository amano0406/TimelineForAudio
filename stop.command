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

compose_args=(-f docker-compose.yml)
if [[ -f ".docker/docker-compose.paths.yml" ]]; then
  compose_args+=(-f .docker/docker-compose.paths.yml)
fi

if docker info >/dev/null 2>&1; then
  run_compose_locked "${compose_args[@]}" down --remove-orphans
else
  echo "Docker Desktop is installed but the Docker engine is not ready."
  echo "Start Docker Desktop and wait until the engine is running, then try again."
  exit 1
fi
