from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from timeline_for_audio_worker.runtime_profile import (
    HIGH_QUALITY_RECOMMENDED_GPU_MEMORY_GIB,
    HIGH_QUALITY_WARNING_GPU_MEMORY_GIB,
    assert_runtime_supports_compute_mode,
    resolve_diarization_default,
    resolve_runtime_lane,
)


class RuntimeProfileTests(unittest.TestCase):
    def test_resolve_runtime_lane_maps_cpu_and_gpu_lanes(self) -> None:
        lanes = {
            "cpu": resolve_runtime_lane("cpu"),
            "gpu": resolve_runtime_lane("gpu"),
        }

        self.assertEqual("medium", lanes["cpu"].model_id)
        self.assertEqual("medium", lanes["gpu"].model_id)
        self.assertEqual(("int8",), lanes["cpu"].compute_types)
        self.assertEqual(("float16", "int8_float16"), lanes["gpu"].compute_types)
        self.assertTrue(lanes["cpu"].diarization_default_enabled)
        self.assertTrue(lanes["gpu"].diarization_default_enabled)

    def test_resolve_diarization_default_is_always_required(self) -> None:
        self.assertTrue(resolve_diarization_default("cpu", token_ready=True))
        self.assertTrue(resolve_diarization_default("cpu", token_ready=False))
        self.assertTrue(resolve_diarization_default("gpu", token_ready=False))
        self.assertTrue(resolve_diarization_default("gpu", token_ready=True))

    def test_gpu_memory_thresholds_match_documented_policy(self) -> None:
        self.assertEqual(8.0, HIGH_QUALITY_WARNING_GPU_MEMORY_GIB)
        self.assertEqual(10.0, HIGH_QUALITY_RECOMMENDED_GPU_MEMORY_GIB)

    def test_gpu_runtime_fails_when_worker_flavor_is_cpu(self) -> None:
        with patch.dict("os.environ", {"TIMELINE_FOR_AUDIO_WORKER_FLAVOR": "cpu"}, clear=False):
            with self.assertRaisesRegex(RuntimeError, "worker container is cpu"):
                assert_runtime_supports_compute_mode("gpu")

    def test_gpu_runtime_fails_when_onnx_cuda_provider_is_missing(self) -> None:
        fake_torch = SimpleNamespace(
            cuda=SimpleNamespace(is_available=lambda: True),
        )
        fake_ort = SimpleNamespace(get_available_providers=lambda: ["CPUExecutionProvider"])

        with (
            patch.dict("os.environ", {"TIMELINE_FOR_AUDIO_WORKER_FLAVOR": "gpu"}, clear=False),
            patch.dict("sys.modules", {"torch": fake_torch, "onnxruntime": fake_ort}),
        ):
            with self.assertRaisesRegex(RuntimeError, "CUDAExecutionProvider"):
                assert_runtime_supports_compute_mode("gpu")

    def test_gpu_runtime_accepts_gpu_worker_with_cuda_providers(self) -> None:
        fake_torch = SimpleNamespace(
            cuda=SimpleNamespace(is_available=lambda: True),
        )
        fake_ort = SimpleNamespace(
            get_available_providers=lambda: [
                "CUDAExecutionProvider",
                "CPUExecutionProvider",
            ]
        )

        with (
            patch.dict("os.environ", {"TIMELINE_FOR_AUDIO_WORKER_FLAVOR": "gpu"}, clear=False),
            patch.dict("sys.modules", {"torch": fake_torch, "onnxruntime": fake_ort}),
        ):
            assert_runtime_supports_compute_mode("gpu")


if __name__ == "__main__":
    unittest.main()
