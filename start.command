#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"

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

compose_args=(-f docker-compose.yml)
if command -v nvidia-smi >/dev/null 2>&1; then
  compose_args+=(-f docker-compose.gpu.yml)
  echo "NVIDIA GPU detected. Starting GPU worker image."
fi

echo "Building and starting the worker container..."
docker compose "${compose_args[@]}" up --build -d worker

echo
echo "TimelineForAudio worker is running."
echo
echo "CLI examples:"
echo "  export PYTHONPATH=worker/src"
echo "  python -m timeline_for_audio_worker settings status"
echo "  python -m timeline_for_audio_worker jobs create --file /path/to/audio.mp3"
echo "  python -m timeline_for_audio_worker jobs list"
echo
echo "Docker status:"
docker compose ps
