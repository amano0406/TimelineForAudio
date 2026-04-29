from __future__ import annotations

import unittest

from timeline_for_audio_worker.acoustic_units import _providers_for_compute_mode


class AcousticUnitTests(unittest.TestCase):
    def test_gpu_mode_prefers_cuda_execution_provider(self) -> None:
        class FakeOrt:
            @staticmethod
            def get_available_providers() -> list[str]:
                return ["CUDAExecutionProvider", "CPUExecutionProvider"]

        providers, warnings = _providers_for_compute_mode(FakeOrt, "gpu")

        self.assertEqual(["CUDAExecutionProvider", "CPUExecutionProvider"], providers)
        self.assertEqual([], warnings)

    def test_gpu_mode_falls_back_to_cpu_with_warning_when_cuda_provider_is_missing(self) -> None:
        class FakeOrt:
            @staticmethod
            def get_available_providers() -> list[str]:
                return ["CPUExecutionProvider"]

        providers, warnings = _providers_for_compute_mode(FakeOrt, "gpu")

        self.assertEqual(["CPUExecutionProvider"], providers)
        self.assertIn("CUDAExecutionProvider", warnings[0])

    def test_cpu_mode_uses_cpu_execution_provider(self) -> None:
        class FakeOrt:
            @staticmethod
            def get_available_providers() -> list[str]:
                return ["CUDAExecutionProvider", "CPUExecutionProvider"]

        providers, warnings = _providers_for_compute_mode(FakeOrt, "cpu")

        self.assertEqual(["CPUExecutionProvider"], providers)
        self.assertEqual([], warnings)


if __name__ == "__main__":
    unittest.main()
