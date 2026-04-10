from __future__ import annotations

import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import patch

from timeline_for_audio_worker import processor
from timeline_for_audio_worker.contracts import InputItem, JobRequest, ManifestItem


class ProcessorQueueTests(unittest.TestCase):
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
