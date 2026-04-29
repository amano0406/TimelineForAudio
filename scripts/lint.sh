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

python_cmd="$(find_python)"
if [ -z "$python_cmd" ]; then
  echo "Python was not found. Create .venv or install Python before committing."
  exit 1
fi

if "$python_cmd" -m ruff --version >/dev/null 2>&1; then
  echo "Running Python lint..."
  "$python_cmd" -m ruff check worker/src worker/tests
  "$python_cmd" -m ruff format --check worker/src worker/tests
else
  echo "ruff is not installed; skipping ruff checks."
fi

echo "Running Python syntax check..."
"$python_cmd" -m compileall -q worker/src worker/tests

echo "Running Python tests..."
PYTHONPATH=worker/src "$python_cmd" -m unittest discover -s worker/tests -p 'test_*.py'
