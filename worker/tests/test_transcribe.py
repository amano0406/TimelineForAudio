from __future__ import annotations

import unittest

from timeline_for_audio_worker.transcribe import (
    _candidate_batch_sizes,
    _initial_batch_size,
    _is_cuda_oom,
    _is_cuda_runtime_failure,
    _load_model_with_fallback,
)


class TranscribeHelpersTests(unittest.TestCase):
    def test_high_quality_gpu_uses_conservative_initial_batch_size(self) -> None:
        self.assertEqual(4, _initial_batch_size("cuda", "high"))

    def test_standard_gpu_uses_larger_initial_batch_size(self) -> None:
        self.assertEqual(16, _initial_batch_size("cuda", "standard"))

    def test_candidate_batch_sizes_are_unique_and_descending(self) -> None:
        self.assertEqual([16, 12, 8, 6, 4, 2, 1], _candidate_batch_sizes(16))
        self.assertEqual([4, 2, 1], _candidate_batch_sizes(4))

    def test_cuda_oom_detection_handles_generic_cuda_error_text(self) -> None:
        error = RuntimeError("CUDA failed with error out of memory")
        self.assertTrue(_is_cuda_oom(error))
        self.assertFalse(_is_cuda_oom(RuntimeError("some other failure")))

    def test_cuda_runtime_failure_detection_handles_generic_cuda_errors(self) -> None:
        error = RuntimeError("CUDA failed with error unknown error")
        self.assertTrue(_is_cuda_runtime_failure(error))
        self.assertFalse(_is_cuda_runtime_failure(RuntimeError("plain cpu failure")))

    def test_gpu_model_load_falls_back_to_cpu_after_repeated_cuda_failures(self) -> None:
        warnings: list[str] = []
        calls: list[tuple[str, str]] = []

        class FakeCuda:
            @staticmethod
            def is_available() -> bool:
                return True

            @staticmethod
            def empty_cache() -> None:
                return None

        class FakeTorch:
            cuda = FakeCuda()

        def load_model(device: str, compute_type: str) -> object:
            calls.append((device, compute_type))
            if device == "cuda":
                raise RuntimeError("CUDA failed with error unknown error")
            return object()

        model, device, compute_type, batch_size = _load_model_with_fallback(
            load_model=load_model,
            torch_module=FakeTorch(),
            initial_device="cuda",
            initial_compute_type="float16",
            initial_batch_size=4,
            transcription_warnings=warnings,
        )

        self.assertIsNotNone(model)
        self.assertEqual("cpu", device)
        self.assertEqual("int8", compute_type)
        self.assertEqual(4, batch_size)
        self.assertEqual(
            [
                ("cuda", "float16"),
                ("cuda", "int8_float16"),
                ("cpu", "int8"),
            ],
            calls,
        )
        self.assertEqual(
            [
                "Primary GPU compute type failed to load; using int8_float16 instead.",
                "GPU model loading failed; transcription fell back to CPU.",
            ],
            warnings,
        )


if __name__ == "__main__":
    unittest.main()
