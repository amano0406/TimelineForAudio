#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"
DOCKER_DESKTOP_URL="https://docs.docker.com/desktop/setup/install/mac-install/"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker Desktop is not installed or docker is not on PATH."
  echo "Download and install Docker Desktop here:"
  echo "  ${DOCKER_DESKTOP_URL}"
  if [ "${TIMELINE_FOR_AUDIO_SKIP_HELP_LINK:-0}" != "1" ]; then
    open "${DOCKER_DESKTOP_URL}" || true
  fi
  echo "Install Docker Desktop, start it, and try again."
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "Docker Desktop is installed but the Docker engine is not ready."
  echo "Docker Desktop setup guide:"
  echo "  ${DOCKER_DESKTOP_URL}"
  if [ "${TIMELINE_FOR_AUDIO_SKIP_HELP_LINK:-0}" != "1" ]; then
    open "${DOCKER_DESKTOP_URL}" || true
  fi
  echo "Start Docker Desktop and wait until the engine is running, then try again."
  exit 1
fi

if [ ! -f ".env" ]; then
  cp ".env.example" ".env"
  echo "Created .env from .env.example."
fi

read_env_value() {
  local key="$1"
  grep -E "^${key}=" .env | tail -n 1 | cut -d'=' -f2-
}

open_app_window() {
  local app_name="$1"
  if [ -d "/Applications/${app_name}.app" ]; then
    open -na "${app_name}" --args --app="${APP_URL}" --window-size="${APP_WINDOW_SIZE}"
    return 0
  fi
  return 1
}

WEB_PORT="$(read_env_value TIMELINE_FOR_AUDIO_WEB_PORT)"
if [ -z "${WEB_PORT}" ]; then
  WEB_PORT="19100"
fi

APP_URL="http://localhost:${WEB_PORT}"
APP_WINDOW_SIZE="960,640"

echo "Starting web and worker containers..."
compose_args=(-f docker-compose.yml)
if command -v nvidia-smi >/dev/null 2>&1; then
  compose_args+=(-f docker-compose.gpu.yml)
  echo "NVIDIA GPU detected. Starting worker with GPU support enabled."
fi
docker compose "${compose_args[@]}" up --build -d

echo "Waiting for containers and web health check..."
for _ in $(seq 1 45); do
  running_services="$(docker compose ps --services --status running || true)"
  if echo "$running_services" | grep -qx "web" && echo "$running_services" | grep -qx "worker"; then
    if curl -fsS "http://localhost:${WEB_PORT}" >/dev/null 2>&1; then
      echo "TimelineForAudio is ready at http://localhost:${WEB_PORT}"
      if [ "${TIMELINE_FOR_AUDIO_SKIP_BROWSER_OPEN:-0}" = "1" ]; then
        exit 0
      fi
      if open_app_window "Google Chrome" || open_app_window "Microsoft Edge" || open_app_window "Brave Browser" || open_app_window "Chromium"; then
        exit 0
      fi
      echo "No supported Chromium-based app-mode browser was found. Opening the default browser instead."
      open "${APP_URL}"
      exit 0
    fi
  fi
  sleep 2
done

echo "TimelineForAudio did not become ready in time."
echo
docker compose ps || true
echo
echo "Last container logs:"
docker compose logs --tail 40 web worker || true
exit 1
