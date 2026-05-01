from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from timeline_for_audio_worker.evaluation import (
    evaluate_turn_artifacts,
    render_evaluation_markdown,
    resolve_run_prediction_path,
    write_evaluation_report,
)


class EvaluationTests(unittest.TestCase):
    def test_evaluate_turn_artifacts_scores_acoustic_units_and_speakers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prediction = root / "prediction.json"
            reference = root / "reference.json"
            reference.write_text(
                json.dumps(
                    {
                        "turns": [
                            {
                                "start": 0.0,
                                "end": 1.0,
                                "speaker": "SPEAKER_00",
                                "text": "こんにちは",
                                "acoustic_units": "ko n ni chi wa",
                            },
                            {
                                "start": 1.0,
                                "end": 2.0,
                                "speaker": "SPEAKER_01",
                                "text": "よろしく",
                                "acoustic_units": "yo ro shi ku",
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            prediction.write_text(
                json.dumps(
                    {
                        "turns": [
                            {
                                "start": 0.0,
                                "end": 1.0,
                                "speaker": "SPEAKER_00",
                                "text": "こんにちは",
                                "acoustic_units": "ko n ni chi wa",
                            },
                            {
                                "start": 1.0,
                                "end": 2.0,
                                "speaker": "SPEAKER_00",
                                "text": "よろしく",
                                "acoustic_units": "yo ro shi ku",
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = evaluate_turn_artifacts(prediction, reference)

        self.assertEqual(2, result["prediction_turns"])
        self.assertEqual(2, result["reference_turns"])
        self.assertEqual(0.0, result["text"]["cer"])
        self.assertEqual(0.0, result["acoustic_units"]["error_rate"])
        self.assertEqual(0.5, result["speaker"]["label_accuracy"])
        self.assertEqual(0.5, result["speaker"]["time_mismatch_rate"])

    def test_evaluate_turn_artifacts_returns_none_for_missing_reference_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prediction = root / "prediction.json"
            reference = root / "reference.json"
            prediction.write_text(json.dumps({"turns": [{"text": "abc"}]}), encoding="utf-8")
            reference.write_text(json.dumps({"turns": [{}]}), encoding="utf-8")

            result = evaluate_turn_artifacts(prediction, reference)

        self.assertIsNone(result["text"]["cer"])
        self.assertIsNone(result["acoustic_units"]["error_rate"])
        self.assertIsNone(result["speaker"]["label_accuracy"])
        self.assertIsNone(result["speaker"]["time_mismatch_rate"])

    def test_resolve_run_prediction_path_uses_single_media_item(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = (
                root
                / "media"
                / "media-0001"
                / "timeline.json"
            )
            artifact.parent.mkdir(parents=True)
            artifact.write_text('{"turns":[]}', encoding="utf-8")

            resolved = resolve_run_prediction_path(
                run_dir=root,
                media_id=None,
                artifact_kind="timeline",
            )

        self.assertEqual(artifact, resolved)

    def test_resolve_run_prediction_path_requires_media_id_for_multiple_items(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for media_id in ("media-0001", "media-0002"):
                artifact = (
                    root
                    / "media"
                    / media_id
                    / "timeline.json"
                )
                artifact.parent.mkdir(parents=True)
                artifact.write_text('{"turns":[]}', encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "Media id is required"):
                resolve_run_prediction_path(
                    run_dir=root,
                    media_id=None,
                    artifact_kind="timeline",
                )

    def test_write_evaluation_report_writes_json_and_markdown(self) -> None:
        payload = {
            "prediction_path": "prediction.json",
            "reference_path": "reference.json",
            "prediction_turns": 1,
            "reference_turns": 1,
            "text": {"cer": 0.0},
            "acoustic_units": {"error_rate": 0.0},
            "speaker": {"label_accuracy": 1.0, "time_mismatch_rate": 0.0},
        }
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            report = write_evaluation_report(payload, output_dir)

            markdown = Path(report["evaluation_markdown_path"]).read_text(encoding="utf-8")

        self.assertIn("evaluation.json", report["evaluation_json_path"])
        self.assertIn("EVALUATION.md", report["evaluation_markdown_path"])
        self.assertIn("Text CER", markdown)
        self.assertIn("Speaker Time Mismatch", render_evaluation_markdown(payload))


if __name__ == "__main__":
    unittest.main()
