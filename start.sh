#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
repo_root="$(pwd)"

json_value() {
  local file="$1"
  local path="$2"
  if ! command -v python3 >/dev/null 2>&1 || [[ ! -f "$file" ]]; then
    return 1
  fi
  python3 - "$file" "$path" <<'PY'
import json
import sys

file_path, key_path = sys.argv[1], sys.argv[2]
try:
    with open(file_path, "r", encoding="utf-8-sig") as handle:
        data = json.load(handle)
    value = data
    for part in key_path.split("."):
        if not isinstance(value, dict) or part not in value:
            sys.exit(1)
        value = value[part]
    if value is None:
        sys.exit(1)
    print(value)
except Exception:
    sys.exit(1)
PY
}

sanitize_name() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9_-' '-' | sed 's/^-//;s/-$//'
}

host_root_default() {
  if [[ -n "${HOME:-}" && -d "$HOME" ]]; then
    printf '%s\n' "$HOME"
  else
    printf '%s\n' "$repo_root"
  fi
}

path_mappings_json() {
  local host_root="$1"
  if command -v python3 >/dev/null 2>&1; then
    python3 - "$host_root" <<'PY'
import json
import sys

print(json.dumps([{"host": sys.argv[1], "container": "/host"}], ensure_ascii=False))
PY
  else
    printf '[{"host":"%s","container":"/host"}]\n' "$host_root"
  fi
}

run_compose_locked() {
  mkdir -p .docker
  if command -v flock >/dev/null 2>&1; then
    flock .docker/docker-compose.lock docker compose "$@"
  else
    docker compose "$@"
  fi
}

if [[ ! -f settings.json && -f settings.example.json ]]; then
  cp settings.example.json settings.json
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not installed or docker is not on PATH."
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "Docker is installed but the Docker engine is not ready."
  echo "Start Docker and wait until the engine is running, then try again."
  exit 1
fi

api_port="${TIMELINE_FOR_AUDIO_API_PORT:-$(json_value settings.json runtime.apiPort 2>/dev/null || echo 19100)}"
instance_name="${TIMELINE_FOR_AUDIO_INSTANCE_NAME:-$(json_value settings.json runtime.instanceName 2>/dev/null || true)}"
if [[ -z "${instance_name// }" ]]; then
  instance_name="local-$(printf '%s' "$repo_root" | cksum | awk '{print $1}')"
fi
instance_name="$(sanitize_name "$instance_name")"

export TIMELINE_FOR_AUDIO_API_PORT="$api_port"
export TIMELINE_FOR_AUDIO_HOST_ROOT="${TIMELINE_FOR_AUDIO_HOST_ROOT:-$(host_root_default)}"
export TIMELINE_FOR_AUDIO_PATH_MAPPINGS="${TIMELINE_FOR_AUDIO_PATH_MAPPINGS:-$(path_mappings_json "$TIMELINE_FOR_AUDIO_HOST_ROOT")}"

compose_args=(-p "timeline-for-audio-${instance_name}" -f docker-compose.yml)
if [[ "${TIMELINE_FOR_AUDIO_ENABLE_GPU:-0}" == "1" && -f docker-compose.gpu.yml ]]; then
  compose_args+=(-f docker-compose.gpu.yml)
  echo "GPU compose override: enabled by TIMELINE_FOR_AUDIO_ENABLE_GPU=1"
else
  echo "GPU compose override: disabled"
fi

echo "Starting TimelineForAudio worker..."
echo "Instance: $instance_name"
echo "API: http://127.0.0.1:${api_port}/health"

run_compose_locked "${compose_args[@]}" up -d --build --remove-orphans worker

echo
echo "TimelineForAudio worker is running."
echo "Processing does not start automatically; call the local API when needed."
echo
docker compose "${compose_args[@]}" ps
