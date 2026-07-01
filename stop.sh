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

run_compose_locked() {
  mkdir -p .docker
  if command -v flock >/dev/null 2>&1; then
    flock .docker/docker-compose.lock docker compose "$@"
  else
    docker compose "$@"
  fi
}

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not installed or docker is not on PATH."
  exit 1
fi

instance_name="${TIMELINE_FOR_AUDIO_INSTANCE_NAME:-$(json_value settings.json runtime.instanceName 2>/dev/null || true)}"
if [[ -z "${instance_name// }" ]]; then
  instance_name="local-$(printf '%s' "$repo_root" | cksum | awk '{print $1}')"
fi
instance_name="$(sanitize_name "$instance_name")"

compose_args=(-p "timeline-for-audio-${instance_name}" -f docker-compose.yml)

if docker info >/dev/null 2>&1; then
  echo "Stopping TimelineForAudio worker..."
  run_compose_locked "${compose_args[@]}" down --remove-orphans
else
  echo "Docker is installed but the Docker engine is not ready."
  echo "Start Docker and wait until the engine is running, then try again."
  exit 1
fi
