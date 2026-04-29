from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from timeline_for_audio_worker.review_artifact import (
    build_review_data,
    write_process_review_artifact,
    write_review_artifact,
)


class ReviewArtifactTests(unittest.TestCase):
    def test_build_review_data_derives_word_ipa(self) -> None:
        data = build_review_data(
            source_info={
                "display_name": "sample.mp3",
                "duration_seconds": 3.0,
                "language_hint": "ja",
            },
            transcript_payload={
                "words": [
                    {
                        "index": 1,
                        "original_start": 0.1,
                        "original_end": 0.4,
                        "speaker": "SPEAKER_00",
                        "text": "こんにちは",
                    },
                    {
                        "index": 2,
                        "original_start": 0.5,
                        "original_end": 0.8,
                        "speaker": "SPEAKER_01",
                        "text": "はい",
                    },
                ]
            },
            ipa_turns=[
                {
                    "index": 1,
                    "start": 0.1,
                    "end": 0.8,
                    "speaker": "SPEAKER_00",
                    "ipa": "/konnitɕiwa hai/",
                }
            ],
            speaker_count=2,
        )

        self.assertEqual("sample.mp3", data["source_file"])
        self.assertEqual(2, data["speaker_count"])
        self.assertEqual(2, len(data["words"]))
        self.assertEqual("SPEAKER_01", data["words"][1]["speaker"])
        self.assertTrue(data["words"][0]["ipa"].startswith("/"))

    def test_build_review_data_prefers_japanese_morphemes_over_raw_character_words(self) -> None:
        data = build_review_data(
            source_info={
                "display_name": "sample.mp3",
                "duration_seconds": 3.0,
                "language_hint": "ja",
            },
            transcript_payload={
                "segments": [
                    {
                        "index": 1,
                        "original_start": 0.0,
                        "original_end": 3.0,
                        "speaker": "SPEAKER_00",
                        "text": "投資家に投資する",
                    }
                ],
                "words": [
                    {
                        "index": 1,
                        "original_start": 0.0,
                        "original_end": 0.2,
                        "speaker": "SPEAKER_00",
                        "text": "投",
                    },
                    {
                        "index": 2,
                        "original_start": 0.2,
                        "original_end": 0.4,
                        "speaker": "SPEAKER_00",
                        "text": "資",
                    },
                ],
            },
            ipa_turns=[
                {
                    "index": 1,
                    "start": 0.0,
                    "end": 3.0,
                    "speaker": "SPEAKER_00",
                    "ipa": "/toɯɕika ni toɯɕi sɯɾɯ/",
                }
            ],
            speaker_count=1,
        )

        texts = [word["text"] for word in data["words"]]
        self.assertIn("投資", "".join(texts))
        self.assertNotEqual(["投", "資"], texts[:2])
        self.assertEqual(
            set(),
            {"word_timestamp"} & {word["timing_source"] for word in data["words"]},
        )
        self.assertTrue(
            {word["timing_source"] for word in data["words"]}.issubset(
                {"morpheme_approximation", "phrase_approximation"}
            )
        )

    def test_write_review_artifact_writes_self_contained_html_and_json(self) -> None:
        with TemporaryDirectory() as temp_dir:
            media_dir = Path(temp_dir) / "media" / "sample"
            data = write_review_artifact(
                media_dir=media_dir,
                source_info={
                    "display_name": "sample.mp3",
                    "duration_seconds": 1.0,
                    "language_hint": "ja",
                },
                transcript_payload={
                    "words": [
                        {
                            "index": 1,
                            "original_start": 0.0,
                            "original_end": 0.5,
                            "speaker": "SPEAKER_00",
                            "text": "はい",
                        }
                    ]
                },
                ipa_turns=[
                    {
                        "index": 1,
                        "start": 0.0,
                        "end": 0.5,
                        "speaker": "SPEAKER_00",
                        "ipa": "/hai/",
                    }
                ],
                speaker_count=1,
            )

            review_html = media_dir / "review" / "review.html"
            review_json = media_dir / "review" / "review_data.json"
            self.assertTrue(review_html.exists())
            self.assertTrue(review_json.exists())
            self.assertIn("IPA Review", review_html.read_text(encoding="utf-8"))
            self.assertIn("IPA token", review_html.read_text(encoding="utf-8"))
            self.assertNotIn("<span>${word.text", review_html.read_text(encoding="utf-8"))
            saved = json.loads(review_json.read_text(encoding="utf-8"))
            self.assertEqual(data["words"], saved["words"])

    def test_write_process_review_artifact_writes_flow_links(self) -> None:
        with TemporaryDirectory() as temp_dir:
            media_dir = Path(temp_dir) / "media" / "sample"
            for relative_path in (
                "source.json",
                "audio/source-normalized.wav",
                "audio/normalized.wav",
                "audio/cut_map.json",
                "transcript/turns-source.json",
                "analysis/diarization_turns.json",
                "ipa/IPA.md",
                "ipa/ipa_turns.json",
            ):
                path = media_dir / relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("{}", encoding="utf-8")

            data = write_process_review_artifact(
                media_dir=media_dir,
                source_info={
                    "display_name": "sample.mp3",
                    "duration_seconds": 60.0,
                    "source_hash": "hash",
                    "generation_signature": "sig",
                    "language_hint": "ja",
                    "diarization_enabled": True,
                    "effective_ipa_backend": "stub-ipa",
                },
                cleanup_source_payload={"segments": [{"text": "cleanup"}]},
                turns_source_payload={
                    "segments": [{"text": "turn"}],
                    "words": [{"text": "word"}],
                    "speaker_turns": [{"speaker": "SPEAKER_00"}],
                    "diarization_used": True,
                },
                timeline_payload={
                    "speech_candidate_count": 2,
                    "silence_or_noise_candidate_count": 1,
                    "events": [{}, {}, {}],
                },
                ipa_turns=[{"ipa": "/hai/"}],
                readable_text_enabled=False,
            )

            process_html = media_dir / "review" / "process.html"
            process_json = media_dir / "review" / "process_data.json"
            self.assertTrue(process_html.exists())
            self.assertTrue(process_json.exists())
            html = process_html.read_text(encoding="utf-8")
            self.assertIn("Processing Review", html)
            self.assertIn("../audio/source-normalized.wav", html)
            self.assertIn("../ipa/IPA.md", html)
            self.assertEqual(2, data["speech_candidate_count"])
            saved = json.loads(process_json.read_text(encoding="utf-8"))
            self.assertEqual("stub-ipa", saved["ipa_backend"])


if __name__ == "__main__":
    unittest.main()
