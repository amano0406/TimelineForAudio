from __future__ import annotations

from pathlib import Path
import json
from types import SimpleNamespace
import unittest
from tempfile import TemporaryDirectory
from unittest.mock import patch

from timeline_for_audio_worker import processor
from timeline_for_audio_worker.contracts import InputItem, RunRequest, ManifestItem


class ProcessorQueueTests(unittest.TestCase):
    def test_process_run_returns_false_when_run_lock_exists(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_dir = root / "run-1"
            run_dir.mkdir()
            source_path = root / "sample.wav"
            source_path.write_bytes(b"audio")

            request = RunRequest(
                schema_version=1,
                run_id="run-1",
                created_at="2026-04-11T12:00:00+09:00",
                output_root_id="runs",
                output_root_path=str(root),
                profile="quality-first",
                compute_mode="cpu",
                pipeline_version="2026-04-29-v3-speaker-acoustic-units1",
                conversion_signature="sig-123",
                acoustic_unit_backend="zipa-large-crctc-300k-onnx-v1",
                acoustic_unit_model_id="anyspeech/zipa-large-crctc-300k",
                diarization_enabled=False,
                diarization_model_id=None,
                vad_backend="ffmpeg-silencedetect",
                vad_model_id="ffmpeg-silencedetect-noise-35db",
                reprocess_duplicates=False,
                token_enabled=False,
                input_items=[
                    InputItem(
                        input_id="item-1",
                        source_kind="upload",
                        source_id="uploads",
                        original_path=str(source_path),
                        display_name="sample.wav",
                        size_bytes=source_path.stat().st_size,
                        uploaded_path=str(source_path),
                    )
                ],
            )
            (run_dir / "request.json").write_text(
                json.dumps(request.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (run_dir / "status.json").write_text(
                json.dumps(
                    {
                        "run_id": "run-1",
                        "state": "running",
                        "updated_at": "2099-01-01T00:00:00+00:00",
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            (run_dir / ".run.lock").write_text("{}", encoding="utf-8")

            with patch.object(processor, "_write_support_docs") as write_support_docs:
                self.assertFalse(processor.process_run(run_dir))

            write_support_docs.assert_not_called()

    def test_process_run_reclaims_stale_run_lock(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_dir = root / "run-1"
            run_dir.mkdir()
            good_path = root / "good.wav"
            good_path.write_bytes(b"good")

            request = RunRequest(
                schema_version=1,
                run_id="run-1",
                created_at="2026-04-11T12:00:00+09:00",
                output_root_id="runs",
                output_root_path=str(root),
                profile="quality-first",
                compute_mode="cpu",
                pipeline_version="2026-04-29-v3-speaker-acoustic-units1",
                conversion_signature="sig-123",
                acoustic_unit_backend="zipa-large-crctc-300k-onnx-v1",
                acoustic_unit_model_id="anyspeech/zipa-large-crctc-300k",
                diarization_enabled=False,
                diarization_model_id=None,
                vad_backend="ffmpeg-silencedetect",
                vad_model_id="ffmpeg-silencedetect-noise-35db",
                reprocess_duplicates=False,
                token_enabled=False,
                input_items=[
                    InputItem(
                        input_id="item-1",
                        source_kind="upload",
                        source_id="uploads",
                        original_path=str(good_path),
                        display_name="good.wav",
                        size_bytes=good_path.stat().st_size,
                        uploaded_path=str(good_path),
                    )
                ],
            )
            (run_dir / "request.json").write_text(
                json.dumps(request.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (run_dir / "status.json").write_text(
                json.dumps(
                    {
                        "run_id": "run-1",
                        "state": "running",
                        "updated_at": "2026-04-10T00:00:00+00:00",
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            (run_dir / ".run.lock").write_text("{}", encoding="utf-8")

            def fake_probe_audio(path: Path) -> dict[str, object]:
                return {
                    "size_bytes": good_path.stat().st_size,
                    "duration_seconds": 5.0,
                    "container_name": "wav",
                    "extension": "wav",
                    "audio_codec": "pcm_s16le",
                    "audio_channels": 1,
                    "audio_sample_rate": 16000,
                    "bitrate": 256000,
                    "captured_at": None,
                }

            with (
                patch.object(processor, "_write_support_docs"),
                patch.object(processor, "load_catalog", return_value={}),
                patch.object(processor, "probe_audio", side_effect=fake_probe_audio),
                patch.object(processor, "sha256_file", return_value="good-hash"),
                patch.object(
                    processor,
                    "build_eta_predictor",
                    return_value=type("Predictor", (), {"sample_count": 0})(),
                ),
                patch.object(processor, "_estimate_remaining_with_history", return_value=None),
                patch.object(processor, "_process_one_item", return_value=[]),
                patch.object(processor, "append_catalog_rows"),
            ):
                self.assertTrue(processor.process_run(run_dir))

            self.assertFalse((run_dir / ".run.lock").exists())

    def test_resolve_duplicate_artifact_path_returns_none_for_stale_catalog_entry(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            duplicate = {
                "timeline_path": str(root / "missing-timeline.md"),
                "run_dir": str(root / "missing-run"),
                "media_id": "sample-media",
            }

            self.assertIsNone(processor._resolve_duplicate_artifact_path(duplicate))

    def test_resolve_duplicate_artifact_path_uses_run_dir_when_artifact_path_is_missing(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            timeline_path = (
                root
                / "run-1"
                / "media"
                / "sample-media"
                / "timeline"
                / "speaker-acoustic-units-timeline.json"
            )
            timeline_path.parent.mkdir(parents=True, exist_ok=True)
            timeline_path.write_text('{"turns":[]}', encoding="utf-8")

            duplicate = {
                "timeline_path": str(root / "stale-timeline.md"),
                "run_dir": str(root / "run-1"),
                "media_id": "sample-media",
            }

            self.assertEqual(timeline_path, processor._resolve_duplicate_artifact_path(duplicate))

    def test_process_run_reclaims_stale_running_run_before_pending_queue(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            running_run_dir = root / "run-running"
            pending_run_dir = root / "run-pending"
            running_run_dir.mkdir()
            pending_run_dir.mkdir()
            source_path = root / "sample.wav"
            source_path.write_bytes(b"audio")

            request = RunRequest(
                schema_version=1,
                run_id="run-running",
                created_at="2026-04-11T12:00:00+09:00",
                output_root_id="runs",
                output_root_path=str(root),
                profile="quality-first",
                compute_mode="cpu",
                pipeline_version="2026-04-29-v3-speaker-acoustic-units1",
                conversion_signature="sig-123",
                acoustic_unit_backend="zipa-large-crctc-300k-onnx-v1",
                acoustic_unit_model_id="anyspeech/zipa-large-crctc-300k",
                diarization_enabled=False,
                diarization_model_id=None,
                vad_backend="ffmpeg-silencedetect",
                vad_model_id="ffmpeg-silencedetect-noise-35db",
                reprocess_duplicates=False,
                token_enabled=False,
                input_items=[
                    InputItem(
                        input_id="item-1",
                        source_kind="upload",
                        source_id="uploads",
                        original_path=str(source_path),
                        display_name="sample.wav",
                        size_bytes=source_path.stat().st_size,
                        uploaded_path=str(source_path),
                    )
                ],
            )
            (running_run_dir / "request.json").write_text(
                json.dumps(request.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (running_run_dir / "status.json").write_text(
                json.dumps(
                    {
                        "run_id": "run-running",
                        "state": "running",
                        "updated_at": "2026-04-10T00:00:00+00:00",
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            (running_run_dir / ".run.lock").write_text("{}", encoding="utf-8")
            (pending_run_dir / "request.json").write_text("{}", encoding="utf-8")
            (pending_run_dir / "status.json").write_text(
                json.dumps({"state": "pending"}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            def fake_probe_audio(path: Path) -> dict[str, object]:
                return {
                    "size_bytes": source_path.stat().st_size,
                    "duration_seconds": 5.0,
                    "container_name": "wav",
                    "extension": "wav",
                    "audio_codec": "pcm_s16le",
                    "audio_channels": 1,
                    "audio_sample_rate": 16000,
                    "bitrate": 256000,
                    "captured_at": None,
                }

            with (
                patch.object(processor, "_write_support_docs"),
                patch.object(processor, "load_catalog", return_value={}),
                patch.object(processor, "probe_audio", side_effect=fake_probe_audio),
                patch.object(processor, "sha256_file", return_value="good-hash"),
                patch.object(
                    processor,
                    "build_eta_predictor",
                    return_value=type("Predictor", (), {"sample_count": 0})(),
                ),
                patch.object(processor, "_estimate_remaining_with_history", return_value=None),
                patch.object(processor, "_process_one_item", return_value=[]),
                patch.object(processor, "append_catalog_rows"),
                patch.object(processor, "_collect_running_runs", return_value=[running_run_dir]),
                patch.object(processor, "_collect_pending_runs", return_value=[pending_run_dir]),
            ):
                self.assertTrue(processor.process_run())

            running_status = json.loads((running_run_dir / "status.json").read_text(encoding="utf-8"))
            pending_status = json.loads((pending_run_dir / "status.json").read_text(encoding="utf-8"))
            self.assertEqual("completed", running_status["state"])
            self.assertEqual("pending", pending_status["state"])

    def test_process_run_waits_for_running_run_before_picking_pending(self) -> None:
        with (
            patch.object(processor, "_collect_running_runs", return_value=[Path("/tmp/run-1")]),
            patch.object(processor, "_collect_pending_runs") as collect_pending,
        ):
            self.assertFalse(processor.process_run())
            collect_pending.assert_not_called()

    def test_process_run_continues_after_preflight_probe_failure(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_dir = root / "run-1"
            run_dir.mkdir()
            bad_path = root / "broken.m4a"
            bad_path.write_bytes(b"broken")
            good_path = root / "good.wav"
            good_path.write_bytes(b"good")

            request = RunRequest(
                schema_version=1,
                run_id="run-1",
                created_at="2026-04-11T12:00:00+09:00",
                output_root_id="runs",
                output_root_path=str(root),
                profile="quality-first",
                compute_mode="cpu",
                pipeline_version="2026-04-29-v3-speaker-acoustic-units1",
                conversion_signature="sig-123",
                acoustic_unit_backend="zipa-large-crctc-300k-onnx-v1",
                acoustic_unit_model_id="anyspeech/zipa-large-crctc-300k",
                diarization_enabled=False,
                diarization_model_id=None,
                vad_backend="ffmpeg-silencedetect",
                vad_model_id="ffmpeg-silencedetect-noise-35db",
                reprocess_duplicates=False,
                token_enabled=False,
                input_items=[
                    InputItem(
                        input_id="item-1",
                        source_kind="upload",
                        source_id="uploads",
                        original_path=str(bad_path),
                        display_name="broken.m4a",
                        size_bytes=bad_path.stat().st_size,
                        uploaded_path=str(bad_path),
                    ),
                    InputItem(
                        input_id="item-2",
                        source_kind="upload",
                        source_id="uploads",
                        original_path=str(good_path),
                        display_name="good.wav",
                        size_bytes=good_path.stat().st_size,
                        uploaded_path=str(good_path),
                    ),
                ],
            )
            (run_dir / "request.json").write_text(
                json.dumps(request.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (run_dir / "status.json").write_text("{}", encoding="utf-8")

            process_calls: list[str] = []

            def fake_probe_audio(path: Path) -> dict[str, object]:
                if path == bad_path:
                    raise RuntimeError("invalid container")
                return {
                    "size_bytes": good_path.stat().st_size,
                    "duration_seconds": 5.0,
                    "container_name": "wav",
                    "extension": "wav",
                    "audio_codec": "pcm_s16le",
                    "audio_channels": 1,
                    "audio_sample_rate": 16000,
                    "bitrate": 256000,
                    "captured_at": None,
                }

            def fake_process_one_item(**kwargs):
                process_calls.append(kwargs["item"].display_name)
                return []

            with (
                patch.object(processor, "_write_support_docs"),
                patch.object(processor, "load_catalog", return_value={}),
                patch.object(processor, "probe_audio", side_effect=fake_probe_audio),
                patch.object(
                    processor,
                    "sha256_file",
                    side_effect=["bad-hash", "good-hash"],
                ),
                patch.object(
                    processor,
                    "build_eta_predictor",
                    return_value=type("Predictor", (), {"sample_count": 0})(),
                ),
                patch.object(processor, "_estimate_remaining_with_history", return_value=None),
                patch.object(processor, "_process_one_item", side_effect=fake_process_one_item),
                patch.object(processor, "append_catalog_rows"),
            ):
                self.assertTrue(processor.process_run(run_dir))

            status_payload = json.loads((run_dir / "status.json").read_text(encoding="utf-8"))
            result_payload = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
            manifest_payload = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))

            self.assertEqual(["good.wav"], process_calls)
            self.assertEqual("completed", status_payload["state"])
            self.assertEqual(1, status_payload["items_done"])
            self.assertEqual(1, status_payload["items_skipped"])
            self.assertEqual(0, status_payload["items_failed"])
            self.assertEqual("Run completed.", status_payload["message"])
            self.assertEqual(1, result_payload["processed_count"])
            self.assertEqual(1, result_payload["skipped_count"])
            self.assertEqual(0, result_payload["error_count"])
            self.assertEqual("skipped_invalid", manifest_payload["items"][0]["status"])
            self.assertEqual("completed", manifest_payload["items"][1]["status"])
            self.assertIn("preflight: skipped 1 invalid audio file(s).", status_payload["warnings"])

    def test_process_run_skips_audio_that_is_too_short(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_dir = root / "run-1"
            run_dir.mkdir()
            short_path = root / "short.m4a"
            short_path.write_bytes(b"short")
            good_path = root / "good.wav"
            good_path.write_bytes(b"good")

            request = RunRequest(
                schema_version=1,
                run_id="run-1",
                created_at="2026-04-11T12:00:00+09:00",
                output_root_id="runs",
                output_root_path=str(root),
                profile="quality-first",
                compute_mode="cpu",
                pipeline_version="2026-04-29-v3-speaker-acoustic-units1",
                conversion_signature="sig-123",
                acoustic_unit_backend="zipa-large-crctc-300k-onnx-v1",
                acoustic_unit_model_id="anyspeech/zipa-large-crctc-300k",
                diarization_enabled=False,
                diarization_model_id=None,
                vad_backend="ffmpeg-silencedetect",
                vad_model_id="ffmpeg-silencedetect-noise-35db",
                reprocess_duplicates=False,
                token_enabled=False,
                input_items=[
                    InputItem(
                        input_id="item-1",
                        source_kind="upload",
                        source_id="uploads",
                        original_path=str(short_path),
                        display_name="short.m4a",
                        size_bytes=short_path.stat().st_size,
                        uploaded_path=str(short_path),
                    ),
                    InputItem(
                        input_id="item-2",
                        source_kind="upload",
                        source_id="uploads",
                        original_path=str(good_path),
                        display_name="good.wav",
                        size_bytes=good_path.stat().st_size,
                        uploaded_path=str(good_path),
                    ),
                ],
            )
            (run_dir / "request.json").write_text(
                json.dumps(request.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (run_dir / "status.json").write_text("{}", encoding="utf-8")

            process_calls: list[str] = []

            def fake_probe_audio(path: Path) -> dict[str, object]:
                if path == short_path:
                    return {
                        "size_bytes": short_path.stat().st_size,
                        "duration_seconds": 1.5,
                        "container_name": "mov,mp4,m4a,3gp,3g2,mj2",
                        "extension": "m4a",
                        "audio_codec": "aac",
                        "audio_channels": 1,
                        "audio_sample_rate": 16000,
                        "bitrate": 64000,
                        "captured_at": None,
                    }
                return {
                    "size_bytes": good_path.stat().st_size,
                    "duration_seconds": 5.0,
                    "container_name": "wav",
                    "extension": "wav",
                    "audio_codec": "pcm_s16le",
                    "audio_channels": 1,
                    "audio_sample_rate": 16000,
                    "bitrate": 256000,
                    "captured_at": None,
                }

            def fake_process_one_item(**kwargs):
                process_calls.append(kwargs["item"].display_name)
                return []

            with (
                patch.object(processor, "_write_support_docs"),
                patch.object(processor, "load_catalog", return_value={}),
                patch.object(processor, "probe_audio", side_effect=fake_probe_audio),
                patch.object(
                    processor,
                    "sha256_file",
                    side_effect=["short-hash", "good-hash"],
                ),
                patch.object(
                    processor,
                    "build_eta_predictor",
                    return_value=type("Predictor", (), {"sample_count": 0})(),
                ),
                patch.object(processor, "_estimate_remaining_with_history", return_value=None),
                patch.object(processor, "_process_one_item", side_effect=fake_process_one_item),
                patch.object(processor, "append_catalog_rows"),
            ):
                self.assertTrue(processor.process_run(run_dir))

            status_payload = json.loads((run_dir / "status.json").read_text(encoding="utf-8"))
            result_payload = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
            manifest_payload = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))

            self.assertEqual(["good.wav"], process_calls)
            self.assertEqual("completed", status_payload["state"])
            self.assertEqual(1, status_payload["items_done"])
            self.assertEqual(1, status_payload["items_skipped"])
            self.assertEqual(0, status_payload["items_failed"])
            self.assertEqual(1, result_payload["processed_count"])
            self.assertEqual(1, result_payload["skipped_count"])
            self.assertEqual(0, result_payload["error_count"])
            self.assertEqual("skipped_too_short", manifest_payload["items"][0]["status"])
            self.assertEqual("completed", manifest_payload["items"][1]["status"])
            self.assertIn(
                "preflight: skipped 1 audio file(s) shorter than 2.0s.",
                status_payload["warnings"],
            )

    def test_process_run_resets_prior_status_on_rerun(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_dir = root / "run-1"
            run_dir.mkdir()
            good_path = root / "good.wav"
            good_path.write_bytes(b"good")

            request = RunRequest(
                schema_version=1,
                run_id="run-1",
                created_at="2026-04-11T12:00:00+09:00",
                output_root_id="runs",
                output_root_path=str(root),
                profile="quality-first",
                compute_mode="cpu",
                pipeline_version="2026-04-29-v3-speaker-acoustic-units1",
                conversion_signature="sig-123",
                acoustic_unit_backend="zipa-large-crctc-300k-onnx-v1",
                acoustic_unit_model_id="anyspeech/zipa-large-crctc-300k",
                diarization_enabled=False,
                diarization_model_id=None,
                vad_backend="ffmpeg-silencedetect",
                vad_model_id="ffmpeg-silencedetect-noise-35db",
                reprocess_duplicates=False,
                token_enabled=False,
                input_items=[
                    InputItem(
                        input_id="item-1",
                        source_kind="upload",
                        source_id="uploads",
                        original_path=str(good_path),
                        display_name="good.wav",
                        size_bytes=good_path.stat().st_size,
                        uploaded_path=str(good_path),
                    )
                ],
            )
            (run_dir / "request.json").write_text(
                json.dumps(request.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (run_dir / "status.json").write_text(
                json.dumps(
                    {
                        "run_id": "run-1",
                        "state": "failed",
                        "current_stage": "failed",
                        "message": "old failure",
                        "warnings": ["stale warning"],
                        "items_total": 1,
                        "items_done": 0,
                        "items_skipped": 9,
                        "items_failed": 7,
                        "processed_duration_sec": 123.0,
                        "total_duration_sec": 321.0,
                        "progress_percent": 100.0,
                        "started_at": "2026-04-10T00:00:00+09:00",
                        "completed_at": "2026-04-10T00:01:00+09:00",
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            def fake_probe_audio(path: Path) -> dict[str, object]:
                return {
                    "size_bytes": good_path.stat().st_size,
                    "duration_seconds": 5.0,
                    "container_name": "wav",
                    "extension": "wav",
                    "audio_codec": "pcm_s16le",
                    "audio_channels": 1,
                    "audio_sample_rate": 16000,
                    "bitrate": 256000,
                    "captured_at": None,
                }

            with (
                patch.object(processor, "_write_support_docs"),
                patch.object(processor, "load_catalog", return_value={}),
                patch.object(processor, "probe_audio", side_effect=fake_probe_audio),
                patch.object(processor, "sha256_file", return_value="good-hash"),
                patch.object(
                    processor,
                    "build_eta_predictor",
                    return_value=type("Predictor", (), {"sample_count": 0})(),
                ),
                patch.object(processor, "_estimate_remaining_with_history", return_value=None),
                patch.object(processor, "_process_one_item", return_value=[]),
                patch.object(processor, "append_catalog_rows"),
            ):
                self.assertTrue(processor.process_run(run_dir))

            status_payload = json.loads((run_dir / "status.json").read_text(encoding="utf-8"))

            self.assertEqual("completed", status_payload["state"])
            self.assertEqual(1, status_payload["items_total"])
            self.assertEqual(1, status_payload["items_done"])
            self.assertEqual(0, status_payload["items_skipped"])
            self.assertEqual(0, status_payload["items_failed"])
            self.assertEqual([], status_payload["warnings"])
            self.assertIsNotNone(status_payload["started_at"])
            self.assertIsNotNone(status_payload["completed_at"])

    def test_process_run_daemon_skips_pending_run_with_unavailable_sources(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            missing_run_dir = root / "run-missing"
            good_run_dir = root / "run-good"
            missing_run_dir.mkdir()
            good_run_dir.mkdir()
            good_path = root / "good.wav"
            good_path.write_bytes(b"good")
            missing_path = root / "missing.wav"

            def write_request(run_dir: Path, run_id: str, source_path: Path) -> None:
                request = RunRequest(
                    schema_version=1,
                    run_id=run_id,
                    created_at="2026-04-11T12:00:00+09:00",
                    output_root_id="runs",
                    output_root_path=str(root),
                    profile="quality-first",
                    compute_mode="cpu",
                    pipeline_version="2026-04-29-v3-speaker-acoustic-units1",
                    conversion_signature=f"sig-{run_id}",
                    acoustic_unit_backend="zipa-large-crctc-300k-onnx-v1",
                    acoustic_unit_model_id="anyspeech/zipa-large-crctc-300k",
                    diarization_enabled=False,
                    diarization_model_id=None,
                    vad_backend="ffmpeg-silencedetect",
                    vad_model_id="ffmpeg-silencedetect-noise-35db",
                    reprocess_duplicates=False,
                    token_enabled=False,
                    input_items=[
                        InputItem(
                            input_id="item-1",
                            source_kind="local_directory",
                            source_id=str(source_path.parent),
                            original_path=str(source_path),
                            display_name=source_path.name,
                            size_bytes=source_path.stat().st_size if source_path.exists() else 0,
                            uploaded_path=None,
                        )
                    ],
                )
                (run_dir / "request.json").write_text(
                    json.dumps(request.to_dict(), ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                (run_dir / "status.json").write_text(
                    json.dumps({"state": "pending"}, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

            write_request(missing_run_dir, "run-missing", missing_path)
            write_request(good_run_dir, "run-good", good_path)

            def fake_probe_audio(path: Path) -> dict[str, object]:
                return {
                    "size_bytes": good_path.stat().st_size,
                    "duration_seconds": 5.0,
                    "container_name": "wav",
                    "extension": "wav",
                    "audio_codec": "pcm_s16le",
                    "audio_channels": 1,
                    "audio_sample_rate": 16000,
                    "bitrate": 256000,
                    "captured_at": None,
                }

            with (
                patch.object(processor, "_collect_running_runs", return_value=[]),
                patch.object(
                    processor,
                    "_collect_pending_runs",
                    return_value=[missing_run_dir, good_run_dir],
                ),
                patch.object(processor, "_write_support_docs"),
                patch.object(processor, "load_catalog", return_value={}),
                patch.object(processor, "probe_audio", side_effect=fake_probe_audio),
                patch.object(processor, "sha256_file", return_value="good-hash"),
                patch.object(
                    processor,
                    "build_eta_predictor",
                    return_value=type("Predictor", (), {"sample_count": 0})(),
                ),
                patch.object(processor, "_estimate_remaining_with_history", return_value=None),
                patch.object(processor, "_process_one_item", return_value=[]),
                patch.object(processor, "append_catalog_rows"),
            ):
                self.assertTrue(processor.process_run())

            missing_status = json.loads((missing_run_dir / "status.json").read_text(encoding="utf-8"))
            good_status = json.loads((good_run_dir / "status.json").read_text(encoding="utf-8"))
            self.assertEqual("pending", missing_status["state"])
            self.assertEqual("completed", good_status["state"])

    def test_collect_pending_runs_skips_delete_requested_runs(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_dir = root / "run-1"
            run_dir.mkdir()
            (run_dir / "request.json").write_text("{}", encoding="utf-8")
            (run_dir / "status.json").write_text(
                json.dumps({"state": "pending"}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (run_dir / ".delete-requested").write_text("requested\n", encoding="utf-8")

            with patch.object(
                processor,
                "load_settings",
                return_value={
                    "outputRoots": [
                        {"id": "runs", "path": str(root), "enabled": True},
                    ]
                },
            ):
                self.assertEqual([], processor._collect_pending_runs())

    def test_process_run_deletes_requested_running_run_and_upload_session(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            uploads_root_dir = root / "uploads"
            session_dir = uploads_root_dir / "session-001"
            session_dir.mkdir(parents=True)
            uploaded_path = session_dir / "sample.wav"
            uploaded_path.write_bytes(b"audio")
            run_dir = root / "run-1"
            run_dir.mkdir()

            request = RunRequest(
                schema_version=1,
                run_id="run-1",
                created_at="2026-04-15T12:00:00+09:00",
                output_root_id="runs",
                output_root_path=str(root),
                profile="quality-first",
                compute_mode="cpu",
                pipeline_version="2026-04-29-v3-speaker-acoustic-units1",
                conversion_signature="sig-123",
                acoustic_unit_backend="zipa-large-crctc-300k-onnx-v1",
                acoustic_unit_model_id="anyspeech/zipa-large-crctc-300k",
                diarization_enabled=False,
                diarization_model_id=None,
                vad_backend="ffmpeg-silencedetect",
                vad_model_id="ffmpeg-silencedetect-noise-35db",
                reprocess_duplicates=False,
                token_enabled=False,
                input_items=[
                    InputItem(
                        input_id="item-1",
                        source_kind="upload",
                        source_id="uploads",
                        original_path=str(uploaded_path),
                        display_name="sample.wav",
                        size_bytes=uploaded_path.stat().st_size,
                        uploaded_path=str(uploaded_path),
                    )
                ],
            )
            (run_dir / "request.json").write_text(
                json.dumps(request.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (run_dir / "status.json").write_text("{}", encoding="utf-8")
            catalog_dir = root / ".timeline-for-audio"
            catalog_dir.mkdir()
            catalog_path = catalog_dir / "catalog.jsonl"
            catalog_path.write_text(
                json.dumps(
                    {
                        "run_id": "run-1",
                        "run_dir": str(run_dir),
                        "source_hash": "good-hash",
                        "conversion_signature": "sig-123",
                        "timeline_path": str(run_dir / "media" / "item-1" / "timeline" / "timeline.md"),
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            def fake_probe_audio(path: Path) -> dict[str, object]:
                return {
                    "size_bytes": uploaded_path.stat().st_size,
                    "duration_seconds": 5.0,
                    "container_name": "wav",
                    "extension": "wav",
                    "audio_codec": "pcm_s16le",
                    "audio_channels": 1,
                    "audio_sample_rate": 16000,
                    "bitrate": 256000,
                    "captured_at": None,
                }

            def fake_process_one_item(**kwargs):
                (run_dir / ".delete-requested").write_text("requested\n", encoding="utf-8")
                kwargs["ensure_not_delete_requested"]("extract_acoustic_units")
                return []

            with (
                patch.object(processor, "uploads_root", return_value=uploads_root_dir),
                patch.object(processor, "_write_support_docs"),
                patch.object(processor, "load_catalog", return_value={}),
                patch.object(processor, "probe_audio", side_effect=fake_probe_audio),
                patch.object(processor, "sha256_file", return_value="good-hash"),
                patch.object(
                    processor,
                    "build_eta_predictor",
                    return_value=type("Predictor", (), {"sample_count": 0})(),
                ),
                patch.object(processor, "_estimate_remaining_with_history", return_value=None),
                patch.object(processor, "_process_one_item", side_effect=fake_process_one_item),
                patch.object(processor, "append_catalog_rows"),
            ):
                self.assertTrue(processor.process_run(run_dir))

            self.assertFalse(run_dir.exists())
            self.assertFalse(session_dir.exists())
            self.assertFalse(catalog_path.exists())

    def test_process_one_item_writes_speaker_acoustic_units_timeline(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_path = root / "sample.wav"
            source_path.write_bytes(b"audio")
            run_dir = root / "run-1"
            run_dir.mkdir()

            request = RunRequest(
                schema_version=1,
                run_id="run-1",
                created_at="2026-04-10T10:00:00+09:00",
                output_root_id="runs",
                output_root_path=str(root),
                profile="quality-first",
                compute_mode="cpu",
                pipeline_version="2026-04-29-v3-speaker-acoustic-units1",
                conversion_signature="sig-123",
                acoustic_unit_backend="zipa-large-crctc-300k-onnx-v1",
                acoustic_unit_model_id="anyspeech/zipa-large-crctc-300k",
                diarization_enabled=True,
                diarization_model_id="pyannote/speaker-diarization-community-1",
                vad_backend="silero-vad",
                vad_model_id="ffmpeg-silencedetect-noise-35db",
                reprocess_duplicates=False,
                token_enabled=True,
                input_items=[],
            )
            item = InputItem(
                input_id="upload-0001",
                source_kind="upload",
                source_id="uploads",
                original_path=str(source_path),
                display_name="sample.wav",
                size_bytes=source_path.stat().st_size,
                uploaded_path=str(source_path),
            )
            manifest_item = ManifestItem(
                input_id=item.input_id,
                source_kind=item.source_kind,
                original_path=item.original_path,
                file_name=item.display_name,
                size_bytes=item.size_bytes,
                duration_seconds=12.0,
                source_hash="abc123",
                conversion_signature="sig-123",
                duplicate_status="new",
                audio_id="sample-abc12345",
                pipeline_version="2026-04-29-v3-speaker-acoustic-units1",
                model_id="anyspeech/zipa-large-crctc-300k",
            )

            def fake_extract_audio(input_path: Path, output_path: Path) -> None:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(b"normalized")

            def fake_trim_audio(
                input_path: Path,
                output_path: Path,
                duration_seconds: float,
                *,
                min_silence_duration_ms: int = 500,
                write_audio: bool = True,
            ):
                self.assertEqual(500, min_silence_duration_ms)
                self.assertFalse(write_audio)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                return [
                    {
                        "original_start": 2.0,
                        "original_end": 4.0,
                        "trimmed_start": 0.0,
                        "trimmed_end": 2.0,
                    }
                ]

            with (
                patch.object(processor, "extract_audio", side_effect=fake_extract_audio),
                patch.object(processor, "trim_audio", side_effect=fake_trim_audio),
                patch.object(
                    processor,
                    "generate_speaker_turns",
                    return_value={
                        "schema_version": 1,
                        "backend": "pyannote.audio",
                        "model_id": "pyannote/speaker-diarization-community-1",
                        "status": "ok",
                        "turn_count": 1,
                        "turns": [{"start": 2.0, "end": 4.0, "speaker": "SPEAKER_01"}],
                    },
                ),
                patch.object(
                    processor,
                    "generate_acoustic_unit_turns",
                    return_value=SimpleNamespace(
                        backend_name="zipa-stub",
                        model_id="zipa-model",
                        status="ok",
                        unit_type="phone_like",
                        execution_provider="CUDAExecutionProvider",
                        available_execution_providers=("CUDAExecutionProvider", "CPUExecutionProvider"),
                        warnings=[],
                        turns=[
                            SimpleNamespace(
                                index=1,
                                start=2.0,
                                end=4.0,
                                acoustic_units="ko n ni chi wa",
                                confidence=0.91,
                            )
                        ],
                    ),
                ),
            ):
                warnings = processor._process_one_item(
                    run_dir=run_dir,
                    request=request,
                    item=item,
                    manifest_item=manifest_item,
                )

            media_dir = run_dir / "media" / str(manifest_item.media_id)
            timeline_path = media_dir / "timeline" / "speaker-acoustic-units-timeline.json"
            self.assertEqual([], warnings)
            self.assertTrue(timeline_path.exists())
            self.assertTrue((media_dir / "ai-raw" / "speaker-turns.raw.json").exists())
            self.assertTrue((media_dir / "ai-raw" / "acoustic-units.raw.json").exists())
            self.assertTrue((media_dir / "segments" / "speech-candidates.json").exists())
            self.assertFalse((media_dir / "segments" / "speech-candidates.wav").exists())
            raw_acoustic_units = json.loads(
                (media_dir / "ai-raw" / "acoustic-units.raw.json").read_text(encoding="utf-8")
            )
            self.assertEqual("CUDAExecutionProvider", raw_acoustic_units["execution_provider"])
            timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
            self.assertEqual("speaker-acoustic-units-timeline", timeline["artifact_type"])
            self.assertEqual(
                "CUDAExecutionProvider",
                timeline["pipeline"]["acoustic_unit_execution_provider"],
            )
            self.assertEqual("SPEAKER_01", timeline["turns"][0]["speaker"])
            self.assertEqual("ko n ni chi wa", timeline["turns"][0]["acoustic_units"])
            artifacts_payload = json.loads(
                (media_dir / "artifacts.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                "speaker_acoustic_units_timeline",
                artifacts_payload["primary_artifact_kind"],
            )


if __name__ == "__main__":
    unittest.main()
