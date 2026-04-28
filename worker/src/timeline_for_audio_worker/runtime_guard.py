from __future__ import annotations

import os
import sys
from pathlib import Path

ALLOW_HOST_CLI_ENV = "TIMELINE_FOR_AUDIO_ALLOW_HOST_CLI"
WORKER_FLAVOR_ENV = "TIMELINE_FOR_AUDIO_WORKER_FLAVOR"


def _env_flag_enabled(name: str) -> bool:
    return str(os.getenv(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def _is_docker_marker_present() -> bool:
    return Path("/.dockerenv").exists()


def is_running_in_container() -> bool:
    if os.getenv(WORKER_FLAVOR_ENV):
        return True
    if _is_docker_marker_present():
        return True
    return str(os.getenv("container") or "").strip().lower() in {"docker", "podman"}


def is_host_cli_allowed_for_tests() -> bool:
    return _env_flag_enabled(ALLOW_HOST_CLI_ENV)


def assert_cli_runtime_allowed() -> None:
    if is_running_in_container() or is_host_cli_allowed_for_tests():
        return
    message = "\n".join(
        [
            "TimelineForAudio CLI is Docker-only in normal use.",
            "",
            "Use the Docker wrapper from the repository root:",
            "  Windows PowerShell: .\\tfa.ps1 settings status",
            "  WSL/Unix backdoor: ./tfa.command settings status",
            "",
            f"For tests only, set {ALLOW_HOST_CLI_ENV}=1 before running the CLI directly.",
        ]
    )
    print(message, file=sys.stderr)
    raise SystemExit(2)
