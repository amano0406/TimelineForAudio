#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"

COMPOSE_PROJECT="audio2timeline"
APPDATA_VOLUME="${COMPOSE_PROJECT}_app-data"
OUTPUTS_VOLUME="${COMPOSE_PROJECT}_outputs"
UPLOADS_VOLUME="${COMPOSE_PROJECT}_uploads"
HF_CACHE_VOLUME="${COMPOSE_PROJECT}_hf-cache"
TORCH_CACHE_VOLUME="${COMPOSE_PROJECT}_torch-cache"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker Desktop is not installed or docker is not on PATH."
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "Docker Desktop is installed but the Docker engine is not ready."
  echo "Start Docker Desktop and wait until the engine is running, then try again."
  exit 1
fi

echo
echo "audio2timeline uninstall"
echo
echo "This will remove:"
echo "  - Docker containers for this project"
echo "  - Docker images built for this project"
echo "  - temporary Docker volumes for this project"
echo "  - Docker network for this project"
echo
echo "Optional:"
echo "  - delete saved app data volume (includes token and settings)"
if [[ -f ".env" ]]; then
  echo "  - delete local .env"
fi
echo

confirm_yes() {
  local prompt_text="$1"
  local response
  read -r -p "${prompt_text}" response
  case "${response}" in
    y|Y|yes|YES|Yes)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

if ! confirm_yes "Continue with uninstall? (y/n): "; then
  echo "Uninstall canceled."
  exit 1
fi

echo
echo "Stopping and removing Docker resources..."
docker compose -f docker-compose.yml -f docker-compose.gpu.yml down --rmi local --remove-orphans </dev/null

remove_volume_if_exists() {
  local volume_name="$1"
  if docker volume ls --format '{{.Name}}' | grep -Fxq "${volume_name}"; then
    docker volume rm "${volume_name}" >/dev/null
    echo "Removed Docker volume: ${volume_name}"
  fi
}

remove_volume_if_exists "${UPLOADS_VOLUME}"
remove_volume_if_exists "${OUTPUTS_VOLUME}"
remove_volume_if_exists "${HF_CACHE_VOLUME}"
remove_volume_if_exists "${TORCH_CACHE_VOLUME}"

echo
echo "Saved app data volume:"
echo "  ${APPDATA_VOLUME}"
echo "This includes your saved Hugging Face token and app settings."
if confirm_yes "Delete saved token and settings too? (y/n): "; then
  remove_volume_if_exists "${APPDATA_VOLUME}"
  echo "Deleted saved app data volume."
else
  echo "Kept saved token and settings."
fi

echo "Docker resources removed."

if [[ -f ".env" ]]; then
  echo
  if confirm_yes "Delete local .env as well? (y/n): "; then
    rm -f ".env"
    echo "Deleted .env"
  else
    echo "Kept .env"
  fi
fi

echo
echo "Uninstall completed."
