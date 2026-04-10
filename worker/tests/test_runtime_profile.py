from __future__ import annotations

import unittest

from timeline_for_audio_worker.runtime_profile import (
    HIGH_QUALITY_RECOMMENDED_GPU_MEMORY_GIB,
    HIGH_QUALITY_WARNING_GPU_MEMORY_GIB,
    resolve_diarization_default,
    resolve_runtime_lane,
)


class RuntimeProfileTests(unittest.TestCase):
    def test_resolve_runtime_lane_maps_all_four_lanes(self) -> None:
        lanes = {
            ("cpu", "standard"): resolve_runtime_lane("cpu", "standard"),
            ("cpu", "high"): resolve_runtime_lane("cpu", "high"),
            ("gpu", "standard"): resolve_runtime_lane("gpu", "standard"),
            ("gpu", "high"): resolve_runtime_lane("gpu", "high"),
        }

        self.assertEqual("medium", lanes[("cpu", "standard")].model_id)
        self.assertEqual("large-v3", lanes[("cpu", "high")].model_id)
        self.assertEqual("medium", lanes[("gpu", "standard")].model_id)
        self.assertEqual("large-v3", lanes[("gpu", "high")].model_id)
        self.assertEqual(("int8",), lanes[("cpu", "standard")].compute_types)
        self.assertEqual(("int8",), lanes[("cpu", "high")].compute_types)
        self.assertEqual(("float16", "int8_float16"), lanes[("gpu", "standard")].compute_types)
        self.assertEqual(("float16", "int8_float16"), lanes[("gpu", "high")].compute_types)
        self.assertFalse(lanes[("cpu", "standard")].diarization_default_enabled)
        self.assertFalse(lanes[("cpu", "high")].diarization_default_enabled)
        self.assertTrue(lanes[("gpu", "standard")].diarization_default_enabled)
        self.assertTrue(lanes[("gpu", "high")].diarization_default_enabled)

    def test_resolve_diarization_default_is_gpu_only_when_token_ready(self) -> None:
        self.assertFalse(resolve_diarization_default("cpu", token_ready=True))
        self.assertFalse(resolve_diarization_default("cpu", token_ready=False))
        self.assertFalse(resolve_diarization_default("gpu", token_ready=False))
        self.assertTrue(resolve_diarization_default("gpu", token_ready=True))

    def test_gpu_memory_thresholds_match_documented_policy(self) -> None:
        self.assertEqual(8.0, HIGH_QUALITY_WARNING_GPU_MEMORY_GIB)
        self.assertEqual(10.0, HIGH_QUALITY_RECOMMENDED_GPU_MEMORY_GIB)


if __name__ == "__main__":
    unittest.main()
