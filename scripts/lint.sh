#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root"

find_python() {
  if [ -x "$repo_root/.venv/Scripts/python.exe" ]; then
    echo "$repo_root/.venv/Scripts/python.exe"
    return
  fi

  if [ -x "$repo_root/.venv/bin/python" ]; then
    echo "$repo_root/.venv/bin/python"
    return
  fi

  if command -v python >/dev/null 2>&1; then
    command -v python
    return
  fi

  echo ""
}

if ! command -v dotnet >/dev/null 2>&1; then
  echo "dotnet was not found on PATH."
  exit 1
fi

python_cmd="$(find_python)"
if [ -z "$python_cmd" ]; then
  echo "Python was not found. Create .venv or install Python before committing."
  exit 1
fi

echo "Running Python lint..."
"$python_cmd" -m ruff check worker/src worker/tests
"$python_cmd" -m ruff format --check worker/src worker/tests

echo "Running .NET lint..."
dotnet format web/Audio2Timeline.Web.csproj --verify-no-changes --verbosity minimal
dotnet format tests/Audio2Timeline.E2E/Audio2Timeline.E2E.csproj --verify-no-changes --verbosity minimal
