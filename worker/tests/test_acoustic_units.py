from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import timeline_for_audio_worker.acoustic_units as acoustic_units
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

    def test_generate_acoustic_units_splits_long_original_spans(self) -> None:
        loaded = SimpleNamespace(
            execution_provider="CUDAExecutionProvider",
            available_execution_providers=("CUDAExecutionProvider", "CPUExecutionProvider"),
            warnings=(),
        )
        decoded_ranges: list[tuple[float, float]] = []

        def fake_slice_waveform(waveform: object, sample_rate: int, start: float, end: float):
            return (start, end)

        def fake_decode(chunk: tuple[float, float], sample_rate: int, loaded_model: object):
            decoded_ranges.append(chunk)
            return f"phone-{chunk[0]:.0f}-{chunk[1]:.0f}", 0.5

        with (
            patch.object(acoustic_units, "_load_zipa_model", return_value=loaded),
            patch.object(acoustic_units, "_load_waveform", return_value=(object(), 16000)),
            patch.object(acoustic_units, "_slice_waveform", side_effect=fake_slice_waveform),
            patch.object(acoustic_units, "_decode_zipa_waveform", side_effect=fake_decode),
        ):
            result = acoustic_units.generate_acoustic_unit_turns(
                audio_path="source.wav",
                cut_map=[
                    {
                        "original_start": 10.0,
                        "original_end": 75.0,
                        "trimmed_start": 0.0,
                        "trimmed_end": 65.0,
                    }
                ],
                compute_mode="gpu",
                span_time_basis="original",
                max_chunk_seconds=30.0,
            )

        self.assertEqual("ok", result.status)
        self.assertEqual([(10.0, 40.0), (40.0, 70.0), (70.0, 75.0)], decoded_ranges)
        self.assertEqual(1, len(result.turns))
        self.assertEqual(10.0, result.turns[0].start)
        self.assertEqual(75.0, result.turns[0].end)
        self.assertEqual("phone-10-40 phone-40-70 phone-70-75", result.turns[0].acoustic_units)


if __name__ == "__main__":
    unittest.main()
