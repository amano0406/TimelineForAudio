#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p .docker
if command -v flock >/dev/null 2>&1; then
  flock .docker/docker-compose.lock docker compose down --remove-orphans
else
  docker compose down --remove-orphans
fi
