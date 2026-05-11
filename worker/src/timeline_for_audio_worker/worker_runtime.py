from __future__ import annotations

import os
import threading
import time

from .fs_utils import now_iso
from .settings import save_worker_capabilities, save_worker_heartbeat


def start_worker_heartbeat(interval_seconds: int = 5) -> None:
    def heartbeat_loop() -> None:
        while True:
            save_worker_heartbeat(
                {
                    "schema_version": 1,
                    "state": "running",
                    "updated_at": now_iso(),
                    "pid": os.getpid(),
                    "worker_flavor": os.getenv("TIMELINE_FOR_AUDIO_WORKER_FLAVOR", "cpu"),
                }
            )
            time.sleep(max(1, interval_seconds))

    thread = threading.Thread(target=heartbeat_loop, name="worker-heartbeat", daemon=True)
    thread.start()


def write_worker_capabilities() -> None:
    payload: dict[str, object] = {
        "generatedAt": now_iso(),
        "workerFlavor": os.getenv("TIMELINE_FOR_AUDIO_WORKER_FLAVOR", "cpu"),
        "torchInstalled": False,
        "torchCudaBuilt": False,
        "gpuAvailable": False,
        "deviceCount": 0,
        "deviceNames": [],
        "message": "Worker capability report created.",
    }
    try:
        import torch

        payload["torchInstalled"] = True
        payload["torchCudaBuilt"] = bool(torch.backends.cuda.is_built())
        payload["gpuAvailable"] = bool(torch.cuda.is_available())
        payload["deviceCount"] = int(torch.cuda.device_count()) if torch.cuda.is_available() else 0
        payload["deviceNames"] = (
            [torch.cuda.get_device_name(index) for index in range(torch.cuda.device_count())]
            if torch.cuda.is_available()
            else []
        )
        payload["deviceMemoryGiB"] = (
            [
                round(
                    torch.cuda.get_device_properties(index).total_memory / 1024 / 1024 / 1024,
                    1,
                )
                for index in range(torch.cuda.device_count())
            ]
            if torch.cuda.is_available()
            else []
        )
        payload["maxGpuMemoryGiB"] = max(payload["deviceMemoryGiB"], default=0.0)
        payload["message"] = (
            "GPU is available to the worker."
            if payload["gpuAvailable"]
            else "GPU is not available to the worker."
        )
    except Exception as exc:
        payload["message"] = f"Capability check failed: {exc}"
    save_worker_capabilities(payload)
