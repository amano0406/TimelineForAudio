from __future__ import annotations

from pathlib import Path
import json
import unittest
from tempfile import TemporaryDirectory
from unittest.mock import patch

from timeline_for_audio_worker import processor
from timeline_for_audio_worker.contracts import InputItem, JobRequest, ManifestItem


class ProcessorQueueTests(unittest.TestCase):
    def test_process_job_returns_false_when_job_lock_exists(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            job_dir = root / "job-1"
            job_dir.mkdir()
            source_path = root / "sample.wav"
            source_path.write_bytes(b"audio")

            request = JobRequest(
                schema_version=1,
                job_id="job-1",
                created_at="2026-04-11T12:00:00+09:00",
                output_root_id="runs",
                output_root_path=str(root),
                profile="quality-first",
                compute_mode="cpu",
                processing_quality="standard",
                pipeline_version="2026-04-10-2pass1",
                conversion_signature="sig-123",
                transcription_backend="faster-whisper",
                transcription_model_id="medium",
                supplemental_context_text=None,
                second_pass_enabled=True,
                context_builder_version="context-builder-v1",
                diarization_enabled=False,
                diarization_model_id=None,
                vad_backend="faster-whisper",
                vad_model_id="faster-whisper-default",
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
            (job_dir / "request.json").write_text(
                json.dumps(request.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (job_dir / "status.json").write_text(
                json.dumps(
                    {
                        "job_id": "job-1",
                        "state": "running",
                        "updated_at": "2099-01-01T00:00:00+00:00",
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            (job_dir / ".job.lock").write_text("{}", encoding="utf-8")

            with patch.object(processor, "_write_support_docs") as write_support_docs:
                self.assertFalse(processor.process_job(job_dir))

            write_support_docs.assert_not_called()

    def test_process_job_reclaims_stale_job_lock(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            job_dir = root / "job-1"
            job_dir.mkdir()
            good_path = root / "good.wav"
            good_path.write_bytes(b"good")

            request = JobRequest(
                schema_version=1,
                job_id="job-1",
                created_at="2026-04-11T12:00:00+09:00",
                output_root_id="runs",
                output_root_path=str(root),
                profile="quality-first",
                compute_mode="cpu",
                processing_quality="standard",
                pipeline_version="2026-04-10-2pass1",
                conversion_signature="sig-123",
                transcription_backend="faster-whisper",
                transcription_model_id="medium",
                supplemental_context_text=None,
                second_pass_enabled=True,
                context_builder_version="context-builder-v1",
                diarization_enabled=False,
                diarization_model_id=None,
                vad_backend="faster-whisper",
                vad_model_id="faster-whisper-default",
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
            (job_dir / "request.json").write_text(
                json.dumps(request.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (job_dir / "status.json").write_text(
                json.dumps(
                    {
                        "job_id": "job-1",
                        "state": "running",
                        "updated_at": "2026-04-10T00:00:00+00:00",
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            (job_dir / ".job.lock").write_text("{}", encoding="utf-8")

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
                patch.object(processor, "_llm_export", return_value=(0, None)),
                patch.object(processor, "append_catalog_rows"),
            ):
                self.assertTrue(processor.process_job(job_dir))

            self.assertFalse((job_dir / ".job.lock").exists())

    def test_resolve_duplicate_timeline_path_returns_none_for_stale_catalog_entry(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            duplicate = {
                "timeline_path": str(root / "missing-timeline.md"),
                "run_dir": str(root / "missing-run"),
                "media_id": "sample-media",
            }

            self.assertIsNone(processor._resolve_duplicate_timeline_path(duplicate))

    def test_resolve_duplicate_timeline_path_uses_run_dir_when_timeline_path_is_missing(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            timeline_path = root / "job-1" / "media" / "sample-media" / "timeline" / "timeline.md"
            timeline_path.parent.mkdir(parents=True, exist_ok=True)
            timeline_path.write_text("# Timeline\n", encoding="utf-8")

            duplicate = {
                "timeline_path": str(root / "stale-timeline.md"),
                "run_dir": str(root / "job-1"),
                "media_id": "sample-media",
            }

            self.assertEqual(timeline_path, processor._resolve_duplicate_timeline_path(duplicate))

    def test_process_job_waits_for_running_job_before_picking_pending(self) -> None:
        with (
            patch.object(processor, "_collect_running_jobs", return_value=[Path("/tmp/run-1")]),
            patch.object(processor, "_collect_pending_jobs") as collect_pending,
        ):
            self.assertFalse(processor.process_job())
            collect_pending.assert_not_called()

    def test_process_job_continues_after_preflight_probe_failure(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            job_dir = root / "job-1"
            job_dir.mkdir()
            bad_path = root / "broken.m4a"
            bad_path.write_bytes(b"broken")
            good_path = root / "good.wav"
            good_path.write_bytes(b"good")

            request = JobRequest(
                schema_version=1,
                job_id="job-1",
                created_at="2026-04-11T12:00:00+09:00",
                output_root_id="runs",
                output_root_path=str(root),
                profile="quality-first",
                compute_mode="cpu",
                processing_quality="standard",
                pipeline_version="2026-04-10-2pass1",
                conversion_signature="sig-123",
                transcription_backend="faster-whisper",
                transcription_model_id="medium",
                supplemental_context_text=None,
                second_pass_enabled=True,
                context_builder_version="context-builder-v1",
                diarization_enabled=False,
                diarization_model_id=None,
                vad_backend="faster-whisper",
                vad_model_id="faster-whisper-default",
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
            (job_dir / "request.json").write_text(
                json.dumps(request.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (job_dir / "status.json").write_text("{}", encoding="utf-8")

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
                patch.object(processor, "_llm_export", return_value=(0, None)),
                patch.object(processor, "append_catalog_rows"),
            ):
                self.assertTrue(processor.process_job(job_dir))

            status_payload = json.loads((job_dir / "status.json").read_text(encoding="utf-8"))
            result_payload = json.loads((job_dir / "result.json").read_text(encoding="utf-8"))
            manifest_payload = json.loads((job_dir / "manifest.json").read_text(encoding="utf-8"))

            self.assertEqual(["good.wav"], process_calls)
            self.assertEqual("completed", status_payload["state"])
            self.assertEqual(1, status_payload["items_done"])
            self.assertEqual(1, status_payload["items_skipped"])
            self.assertEqual(0, status_payload["items_failed"])
            self.assertEqual("Job completed.", status_payload["message"])
            self.assertEqual(1, result_payload["processed_count"])
            self.assertEqual(1, result_payload["skipped_count"])
            self.assertEqual(0, result_payload["error_count"])
            self.assertEqual("skipped_invalid", manifest_payload["items"][0]["status"])
            self.assertEqual("completed", manifest_payload["items"][1]["status"])
            self.assertIn("preflight: skipped 1 invalid audio file(s).", status_payload["warnings"])

    def test_process_job_skips_audio_that_is_too_short(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            job_dir = root / "job-1"
            job_dir.mkdir()
            short_path = root / "short.m4a"
            short_path.write_bytes(b"short")
            good_path = root / "good.wav"
            good_path.write_bytes(b"good")

            request = JobRequest(
                schema_version=1,
                job_id="job-1",
                created_at="2026-04-11T12:00:00+09:00",
                output_root_id="runs",
                output_root_path=str(root),
                profile="quality-first",
                compute_mode="cpu",
                processing_quality="standard",
                pipeline_version="2026-04-10-2pass1",
                conversion_signature="sig-123",
                transcription_backend="faster-whisper",
                transcription_model_id="medium",
                supplemental_context_text=None,
                second_pass_enabled=True,
                context_builder_version="context-builder-v1",
                diarization_enabled=False,
                diarization_model_id=None,
                vad_backend="faster-whisper",
                vad_model_id="faster-whisper-default",
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
            (job_dir / "request.json").write_text(
                json.dumps(request.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (job_dir / "status.json").write_text("{}", encoding="utf-8")

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
                patch.object(processor, "_llm_export", return_value=(0, None)),
                patch.object(processor, "append_catalog_rows"),
            ):
                self.assertTrue(processor.process_job(job_dir))

            status_payload = json.loads((job_dir / "status.json").read_text(encoding="utf-8"))
            result_payload = json.loads((job_dir / "result.json").read_text(encoding="utf-8"))
            manifest_payload = json.loads((job_dir / "manifest.json").read_text(encoding="utf-8"))

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

    def test_process_job_resets_prior_status_on_rerun(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            job_dir = root / "job-1"
            job_dir.mkdir()
            good_path = root / "good.wav"
            good_path.write_bytes(b"good")

            request = JobRequest(
                schema_version=1,
                job_id="job-1",
                created_at="2026-04-11T12:00:00+09:00",
                output_root_id="runs",
                output_root_path=str(root),
                profile="quality-first",
                compute_mode="cpu",
                processing_quality="standard",
                pipeline_version="2026-04-10-2pass1",
                conversion_signature="sig-123",
                transcription_backend="faster-whisper",
                transcription_model_id="medium",
                supplemental_context_text=None,
                second_pass_enabled=True,
                context_builder_version="context-builder-v1",
                diarization_enabled=False,
                diarization_model_id=None,
                vad_backend="faster-whisper",
                vad_model_id="faster-whisper-default",
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
            (job_dir / "request.json").write_text(
                json.dumps(request.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (job_dir / "status.json").write_text(
                json.dumps(
                    {
                        "job_id": "job-1",
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
                patch.object(processor, "_llm_export", return_value=(0, None)),
                patch.object(processor, "append_catalog_rows"),
            ):
                self.assertTrue(processor.process_job(job_dir))

            status_payload = json.loads((job_dir / "status.json").read_text(encoding="utf-8"))

            self.assertEqual("completed", status_payload["state"])
            self.assertEqual(1, status_payload["items_total"])
            self.assertEqual(1, status_payload["items_done"])
            self.assertEqual(0, status_payload["items_skipped"])
            self.assertEqual(0, status_payload["items_failed"])
            self.assertEqual([], status_payload["warnings"])
            self.assertIsNotNone(status_payload["started_at"])
            self.assertIsNotNone(status_payload["completed_at"])

    def test_process_job_daemon_skips_pending_job_with_unavailable_sources(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            missing_job_dir = root / "job-missing"
            good_job_dir = root / "job-good"
            missing_job_dir.mkdir()
            good_job_dir.mkdir()
            good_path = root / "good.wav"
            good_path.write_bytes(b"good")
            missing_path = root / "missing.wav"

            def write_request(job_dir: Path, job_id: str, source_path: Path) -> None:
                request = JobRequest(
                    schema_version=1,
                    job_id=job_id,
                    created_at="2026-04-11T12:00:00+09:00",
                    output_root_id="runs",
                    output_root_path=str(root),
                    profile="quality-first",
                    compute_mode="cpu",
                    processing_quality="standard",
                    pipeline_version="2026-04-10-2pass1",
                    conversion_signature=f"sig-{job_id}",
                    transcription_backend="faster-whisper",
                    transcription_model_id="medium",
                    supplemental_context_text=None,
                    second_pass_enabled=True,
                    context_builder_version="context-builder-v1",
                    diarization_enabled=False,
                    diarization_model_id=None,
                    vad_backend="faster-whisper",
                    vad_model_id="faster-whisper-default",
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
                (job_dir / "request.json").write_text(
                    json.dumps(request.to_dict(), ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                (job_dir / "status.json").write_text(
                    json.dumps({"state": "pending"}, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

            write_request(missing_job_dir, "job-missing", missing_path)
            write_request(good_job_dir, "job-good", good_path)

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
                patch.object(processor, "_collect_running_jobs", return_value=[]),
                patch.object(
                    processor,
                    "_collect_pending_jobs",
                    return_value=[missing_job_dir, good_job_dir],
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
                patch.object(processor, "_llm_export", return_value=(0, None)),
                patch.object(processor, "append_catalog_rows"),
            ):
                self.assertTrue(processor.process_job())

            missing_status = json.loads((missing_job_dir / "status.json").read_text(encoding="utf-8"))
            good_status = json.loads((good_job_dir / "status.json").read_text(encoding="utf-8"))
            self.assertEqual("pending", missing_status["state"])
            self.assertEqual("completed", good_status["state"])

    def test_collect_pending_jobs_skips_delete_requested_runs(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            job_dir = root / "job-1"
            job_dir.mkdir()
            (job_dir / "request.json").write_text("{}", encoding="utf-8")
            (job_dir / "status.json").write_text(
                json.dumps({"state": "pending"}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (job_dir / ".delete-requested").write_text("requested\n", encoding="utf-8")

            with patch.object(
                processor,
                "load_settings",
                return_value={
                    "outputRoots": [
                        {"id": "runs", "path": str(root), "enabled": True},
                    ]
                },
            ):
                self.assertEqual([], processor._collect_pending_jobs())

    def test_process_job_deletes_requested_running_job_and_upload_session(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            uploads_root_dir = root / "uploads"
            session_dir = uploads_root_dir / "session-001"
            session_dir.mkdir(parents=True)
            uploaded_path = session_dir / "sample.wav"
            uploaded_path.write_bytes(b"audio")
            job_dir = root / "job-1"
            job_dir.mkdir()

            request = JobRequest(
                schema_version=1,
                job_id="job-1",
                created_at="2026-04-15T12:00:00+09:00",
                output_root_id="runs",
                output_root_path=str(root),
                profile="quality-first",
                compute_mode="cpu",
                processing_quality="standard",
                pipeline_version="2026-04-10-2pass1",
                conversion_signature="sig-123",
                transcription_backend="faster-whisper",
                transcription_model_id="medium",
                supplemental_context_text=None,
                second_pass_enabled=True,
                context_builder_version="context-builder-v1",
                diarization_enabled=False,
                diarization_model_id=None,
                vad_backend="faster-whisper",
                vad_model_id="faster-whisper-default",
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
            (job_dir / "request.json").write_text(
                json.dumps(request.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (job_dir / "status.json").write_text("{}", encoding="utf-8")
            catalog_dir = root / ".timeline-for-audio"
            catalog_dir.mkdir()
            catalog_path = catalog_dir / "catalog.jsonl"
            catalog_path.write_text(
                json.dumps(
                    {
                        "job_id": "job-1",
                        "run_dir": str(job_dir),
                        "source_hash": "good-hash",
                        "conversion_signature": "sig-123",
                        "timeline_path": str(job_dir / "media" / "item-1" / "timeline" / "timeline.md"),
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
                (job_dir / ".delete-requested").write_text("requested\n", encoding="utf-8")
                kwargs["ensure_not_delete_requested"]("transcribe_pass2")
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
                patch.object(processor, "_llm_export", return_value=(0, None)),
                patch.object(processor, "append_catalog_rows"),
            ):
                self.assertTrue(processor.process_job(job_dir))

            self.assertFalse(job_dir.exists())
            self.assertFalse(session_dir.exists())
            self.assertFalse(catalog_path.exists())

    def test_process_one_item_runs_two_pass_transcription_and_renders_from_pass2(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_path = root / "sample.wav"
            source_path.write_bytes(b"audio")
            job_dir = root / "job-1"
            job_dir.mkdir()

            request = JobRequest(
                schema_version=1,
                job_id="job-1",
                created_at="2026-04-10T10:00:00+09:00",
                output_root_id="runs",
                output_root_path=str(root),
                profile="quality-first",
                compute_mode="cpu",
                processing_quality="standard",
                pipeline_version="2026-04-10-2pass1",
                conversion_signature="sig-123",
                transcription_backend="faster-whisper",
                transcription_model_id="medium",
                supplemental_context_text="Known spelling: TimelineForAudio",
                second_pass_enabled=True,
                context_builder_version="context-builder-v1",
                diarization_enabled=True,
                diarization_model_id="pyannote/speaker-diarization-community-1",
                vad_backend="silero-vad",
                vad_model_id="faster-whisper-default",
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
                pipeline_version="2026-04-10-2pass1",
                model_id="medium",
            )

            transcribe_calls: list[dict[str, object]] = []

            def fake_extract_audio(input_path: Path, output_path: Path) -> None:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(b"normalized")

            def fake_transcribe_audio(**kwargs):
                transcribe_calls.append(kwargs)
                pass_name = kwargs["pass_name"]
                if pass_name == "pass1":
                    return {
                        "pass_name": "pass1",
                        "diarization_used": False,
                        "segments": [
                            {
                                "index": 1,
                                "speaker": "SPEAKER_00",
                                "text": "first pass text",
                                "original_start": 0.0,
                                "original_end": 1.0,
                            }
                        ],
                        "speaker_turns": [],
                    }
                return {
                    "pass_name": "pass2",
                    "diarization_used": True,
                    "segments": [
                        {
                            "index": 1,
                            "speaker": "SPEAKER_01",
                            "text": "second pass text",
                            "original_start": 0.0,
                            "original_end": 1.0,
                        }
                    ],
                    "speaker_turns": [{"start": 0.0, "end": 1.0, "speaker": "SPEAKER_01"}],
                }

            with (
                patch.object(processor, "extract_audio", side_effect=fake_extract_audio),
                patch.object(processor, "transcribe_audio", side_effect=fake_transcribe_audio),
                patch(
                    "timeline_for_audio_worker.processor.build_context_documents",
                    create=True,
                    return_value={
                        "builder_version": "context-builder-v1",
                        "merged_context_length": 12,
                        "merged_context_truncated": False,
                    },
                ) as build_context_documents,
                patch(
                    "timeline_for_audio_worker.processor.write_pass_diff",
                    create=True,
                    return_value={"changed_segment_count": 1},
                ) as write_pass_diff,
                patch(
                    "timeline_for_audio_worker.processor.apply_speaker_diarization",
                    create=True,
                    side_effect=lambda **kwargs: {
                        **kwargs["transcript_payload"],
                        "diarization_used": True,
                        "speaker_turns": [{"start": 0.0, "end": 1.0, "speaker": "SPEAKER_01"}],
                        "speaker_segments": [
                            {
                                "index": 1,
                                "speaker": "SPEAKER_01",
                                "text": "second pass text",
                                "original_start": 0.0,
                                "original_end": 1.0,
                            }
                        ],
                    },
                ) as apply_speaker_diarization,
                patch.object(
                    processor,
                    "write_speaker_summary",
                    return_value={"speaker_count": 1, "diarization_used": True},
                ) as write_speaker_summary,
                patch.object(
                    processor,
                    "analyze_audio",
                    return_value={
                        "pause_summary": {},
                        "loudness_summary": {},
                        "speaking_rate_summary": {},
                        "pitch_summary": {},
                        "speaker_confidence_summary": {},
                        "diarization_quality_summary": {},
                        "optional_voice_feature_summary": {},
                    },
                ) as analyze_audio,
                patch.object(processor, "render_timeline") as render_timeline,
            ):
                warnings = processor._process_one_item(
                    job_dir=job_dir,
                    request=request,
                    item=item,
                    manifest_item=manifest_item,
                )

            self.assertEqual([], warnings)
            self.assertEqual(2, len(transcribe_calls))
            self.assertEqual("pass1", transcribe_calls[0]["pass_name"])
            self.assertFalse(transcribe_calls[0]["diarization_enabled"])
            self.assertEqual("pass2", transcribe_calls[1]["pass_name"])
            self.assertTrue(transcribe_calls[1]["diarization_enabled"])
            self.assertEqual("pass2", apply_speaker_diarization.call_args.kwargs["transcript_payload"]["pass_name"])
            self.assertEqual("Known spelling: TimelineForAudio", build_context_documents.call_args.kwargs["supplemental_context_text"])
            self.assertEqual("pass1", write_pass_diff.call_args.kwargs["pass1_payload"]["pass_name"])
            self.assertEqual("pass2", write_pass_diff.call_args.kwargs["pass2_payload"]["pass_name"])
            self.assertEqual("pass2", write_speaker_summary.call_args.kwargs["transcript_payload"]["pass_name"])
            self.assertEqual("pass2", analyze_audio.call_args.kwargs["transcript_payload"]["pass_name"])
            self.assertEqual("pass2", render_timeline.call_args.kwargs["transcript_payload"]["pass_name"])


if __name__ == "__main__":
    unittest.main()


