from __future__ import annotations

import json
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any

from .config import ChangeDetectionConfig
from .ffmpeg_utils import extract_frame
from .fs_utils import ensure_dir


def candidate_timestamps(duration_seconds: float) -> list[float]:
    if duration_seconds <= 1.0:
        return [0.0]

    count = max(4, min(16, int(duration_seconds // 30) + 4))
    if duration_seconds <= 12:
        count = 3

    step = duration_seconds / max(count - 1, 1)
    safe_end = max(0.0, duration_seconds - 0.05)
    timestamps: list[float] = []
    for idx in range(count):
        raw_value = idx * step
        safe_value = round(min(safe_end, raw_value), 3)
        if timestamps and abs(timestamps[-1] - safe_value) < 0.001:
            continue
        timestamps.append(safe_value)

    return timestamps or [0.0]


def normalize_processing_quality(value: str | None) -> str:
    return "high" if str(value or "").strip().lower() == "high" else "standard"


def resolve_caption_model_id_for_quality(value: str | None) -> str:
    _ = normalize_processing_quality(value)
    return "florence-community/Florence-2-base"


@lru_cache(maxsize=2)
def _load_easyocr_reader(use_gpu: bool) -> Any | None:
    try:
        import easyocr
    except Exception:
        return None

    return easyocr.Reader(["ja", "en"], gpu=use_gpu, verbose=False)


@lru_cache(maxsize=4)
def _load_florence_captioner(model_id: str, device: str) -> dict[str, Any] | None:
    try:
        import torch
        from transformers import AutoModelForImageTextToText, AutoProcessor
    except Exception:
        return None

    model_kwargs: dict[str, Any] = {"trust_remote_code": True}
    if device == "cuda":
        model_kwargs["dtype"] = torch.float16

    processor = AutoProcessor.from_pretrained(model_id, trust_remote_code=True)
    model = AutoModelForImageTextToText.from_pretrained(model_id, **model_kwargs)
    model = model.to(device)
    model.eval()
    return {
        "model_id": model_id,
        "device": device,
        "processor": processor,
        "model": model,
    }


def _load_ocr_components(
    *, compute_mode: str | None, processing_quality: str | None
) -> tuple[Any | None, Any | None]:
    use_gpu = False
    try:
        import torch

        use_gpu = str(compute_mode or "cpu").lower() == "gpu" and torch.cuda.is_available()
    except Exception:
        use_gpu = False

    caption_model_id = resolve_caption_model_id_for_quality(processing_quality)

    reader = _load_easyocr_reader(use_gpu)
    captioner = _load_florence_captioner(caption_model_id, "cuda" if use_gpu else "cpu")
    return reader, captioner


def _ocr_lines(image_path: Path, reader: Any | None) -> list[str]:
    if reader is None:
        return []

    try:
        rows = reader.readtext(str(image_path), detail=1, paragraph=False)
    except Exception:
        return []

    lines: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 3:
            continue

        text = " ".join(str(row[1] or "").split())
        if len(text) < 2:
            continue

        lowered = text.lower()
        if lowered in seen:
            continue

        seen.add(lowered)
        lines.append(text)
        if len(lines) >= 6:
            break

    return lines


def _caption_text(image_path: Path, captioner: Any | None) -> str:
    if captioner is None:
        return ""

    try:
        import torch
        from PIL import Image

        processor = captioner["processor"]
        model = captioner["model"]
        device = captioner["device"]
        prompt = "<MORE_DETAILED_CAPTION>"

        with Image.open(image_path) as source_image:
            image = source_image.convert("RGB")
            inputs = processor(text=prompt, images=image, return_tensors="pt")

        if "input_ids" not in inputs or "pixel_values" not in inputs:
            return ""

        prepared_inputs: dict[str, Any] = {}
        for key, value in inputs.items():
            if not hasattr(value, "to"):
                prepared_inputs[key] = value
                continue
            if key == "pixel_values":
                prepared_inputs[key] = value.to(device=device, dtype=model.dtype)
                continue
            prepared_inputs[key] = value.to(device)

        with torch.no_grad():
            generated_ids = model.generate(
                input_ids=prepared_inputs["input_ids"],
                pixel_values=prepared_inputs["pixel_values"],
                max_new_tokens=80,
                num_beams=3,
                do_sample=False,
            )

        generated_text = processor.batch_decode(generated_ids, skip_special_tokens=False)[0]
        parsed = processor.post_process_generation(
            generated_text,
            task=prompt,
            image_size=(image.width, image.height),
        )
    except Exception:
        return ""

    if not isinstance(parsed, dict):
        return ""

    candidate = parsed.get(prompt)
    if isinstance(candidate, str) and candidate.strip():
        return " ".join(candidate.split())

    for value in parsed.values():
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())

    return ""


def _summarize(caption: str, ocr_lines: list[str], classification: str) -> str:
    if caption:
        return caption[:280]
    if ocr_lines:
        return f"OCR detected text. Top lines: {' / '.join(ocr_lines[:3])}"
    if classification == "same":
        return "No major visual change."
    if classification == "minor_change":
        return "Minor visual change."
    return "Major visual change detected."


def _frame_retry_timestamps(timestamp: float, duration_seconds: float) -> list[float]:
    safe_end = max(0.0, duration_seconds - 0.05)
    candidates = [
        timestamp,
        min(safe_end, max(0.0, timestamp - 0.25)),
        min(safe_end, max(0.0, timestamp - 0.75)),
        min(safe_end, max(0.0, timestamp - 1.5)),
        safe_end,
        0.0,
    ]
    timestamps: list[float] = []
    for candidate in candidates:
        value = round(candidate, 3)
        if any(abs(existing - value) < 0.001 for existing in timestamps):
            continue
        timestamps.append(value)
    return timestamps


def _extract_frame_best_effort(
    video_path: Path,
    image_path: Path,
    timestamp: float,
    duration_seconds: float,
) -> tuple[float | None, str | None]:
    attempts = _frame_retry_timestamps(timestamp, duration_seconds)
    last_error: subprocess.CalledProcessError | None = None
    for candidate in attempts:
        try:
            extract_frame(video_path, image_path, candidate)
            return candidate, None
        except subprocess.CalledProcessError as exc:
            last_error = exc

    if last_error is None:
        return None, None

    stderr_text = " ".join((last_error.stderr or "").split())
    detail = stderr_text[:240] if stderr_text else f"ffmpeg exited with status {last_error.returncode}"
    return (
        None,
        f"Skipped screenshot at {timestamp:.3f}s after {len(attempts)} ffmpeg attempt(s): {detail}",
    )


def extract_screens(
    *,
    video_path: Path,
    screen_dir: Path,
    duration_seconds: float,
    thresholds: ChangeDetectionConfig,
    compute_mode: str | None,
    processing_quality: str | None,
 ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    from .change_detection import compare_images

    ensure_dir(screen_dir)
    timestamps = candidate_timestamps(duration_seconds)
    frame_rows: list[dict[str, Any]] = []
    diff_rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    reader, captioner = _load_ocr_components(
        compute_mode=compute_mode,
        processing_quality=processing_quality,
    )

    previous_path: Path | None = None
    previous_timestamp: float | None = None
    for idx, timestamp in enumerate(timestamps, start=1):
        image_path = screen_dir / f"screenshot_{idx:02d}.jpg"
        effective_timestamp, warning = _extract_frame_best_effort(
            video_path,
            image_path,
            timestamp,
            duration_seconds,
        )
        if warning:
            warnings.append(warning)
        if effective_timestamp is None:
            continue

        if previous_path is None:
            classification = "major_change"
            diff_row = {
                "index": idx,
                "timestamp": effective_timestamp,
                "classification": classification,
                "previous_timestamp": None,
                "changed": True,
                "diff_summary": "Initial frame.",
            }
        else:
            comparison = compare_images(previous_path, image_path, thresholds)
            classification = comparison.classification
            diff_row = {
                "index": idx,
                "timestamp": effective_timestamp,
                "classification": classification,
                "previous_timestamp": previous_timestamp,
                "changed": comparison.classification != "same",
                "diff_summary": (
                    f"classification={comparison.classification}, "
                    f"phash={comparison.phash_distance}, mean_diff={comparison.mean_diff}"
                ),
            }

        diff_rows.append(diff_row)

        include_note = idx == 1 or classification == "major_change"
        if include_note:
            ocr_lines = _ocr_lines(image_path, reader)
            caption = _caption_text(image_path, captioner)
            frame_rows.append(
                {
                    "index": idx,
                    "timestamp": effective_timestamp,
                    "filename": image_path.name,
                    "summary": _summarize(caption, ocr_lines, classification),
                    "caption": caption,
                    "ocr_lines": ocr_lines,
                    "classification": classification,
                }
            )

        previous_path = image_path
        previous_timestamp = effective_timestamp

    (screen_dir / "screenshots.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in frame_rows)
        + ("\n" if frame_rows else ""),
        encoding="utf-8",
    )
    (screen_dir / "screen_diff.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in diff_rows)
        + ("\n" if diff_rows else ""),
        encoding="utf-8",
    )
    return frame_rows, diff_rows, warnings
