#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"

COMPOSE_PROJECT="timeline-for-audio"
APPDATA_VOLUME="${COMPOSE_PROJECT}_app-data"
CACHE_VOLUME="${COMPOSE_PROJECT}_cache-data"
REMOVE_APP_DATA=0
REMOVE_CACHE=0
REMOVE_SETTINGS=0

for arg in "$@"; do
  case "${arg}" in
    --remove-app-data)
      REMOVE_APP_DATA=1
      ;;
    --remove-cache)
      REMOVE_CACHE=1
      ;;
    --remove-settings)
      REMOVE_SETTINGS=1
      ;;
  esac
done

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
echo "TimelineForAudio uninstall"
echo
echo "This will remove:"
echo "  - Docker containers for this project"
echo "  - Docker images built for this project"
echo "  - Docker network for this project"
echo
echo "Persistent Docker volumes and settings are kept by default."
echo "Optional flags:"
echo "  --remove-app-data   remove run history, catalog cache, ETA history"
echo "  --remove-cache      remove downloaded model cache"
echo "  --remove-settings   remove local settings.json"
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

if [[ "${REMOVE_APP_DATA}" == "1" ]]; then
  remove_volume_if_exists "${APPDATA_VOLUME}"
  echo "Deleted saved app data volume."
else
  echo "Kept Docker volume: ${APPDATA_VOLUME}"
fi

if [[ "${REMOVE_CACHE}" == "1" ]]; then
  remove_volume_if_exists "${CACHE_VOLUME}"
  echo "Deleted cache volume."
else
  echo "Kept Docker volume: ${CACHE_VOLUME}"
fi

echo "Docker resources removed."

if [[ "${REMOVE_SETTINGS}" == "1" && -f "settings.json" ]]; then
  echo
  echo "Local settings file:"
  echo "  $(pwd)/settings.json"
  echo "This includes input/output directories and Hugging Face token."
  if confirm_yes "Delete settings.json? (y/n): "; then
    rm -f "settings.json"
    echo "Deleted settings.json"
  else
    echo "Kept settings.json"
  fi
elif [[ -f "settings.json" ]]; then
  echo "Kept settings.json"
fi

echo
echo "Uninstall completed."
