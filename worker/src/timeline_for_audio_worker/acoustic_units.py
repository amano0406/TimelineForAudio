from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

ACOUSTIC_UNIT_BACKEND = "zipa-large-crctc-300k-onnx-v1"
ACOUSTIC_UNIT_MODEL_ID = "anyspeech/zipa-large-crctc-300k"
ACOUSTIC_UNIT_MODEL_FILE = "model.onnx"
ACOUSTIC_UNIT_TOKENS_FILE = "tokens.txt"
ACOUSTIC_UNIT_TYPE = "phone_like"


@dataclass(frozen=True)
class AcousticUnitTurn:
    index: int
    start: float
    end: float
    acoustic_units: str
    confidence: float | None = None


@dataclass(frozen=True)
class AcousticUnitResult:
    backend_name: str
    model_id: str
    status: str
    unit_type: str
    turns: list[AcousticUnitTurn]
    warnings: list[str]


@dataclass(frozen=True)
class LoadedZipaModel:
    session: Any
    vocab: dict[int, str]
    extractor: Any
    torch_module: Any
    numpy_module: Any


def _compact_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _waveform_duration_seconds(waveform: Any, sample_rate: int) -> float:
    try:
        sample_count = int(waveform.shape[-1])
    except Exception:
        return 0.0
    return sample_count / max(1, int(sample_rate))


def _load_waveform(audio_path: Any) -> tuple[Any, int]:
    try:
        import torchaudio
    except Exception as exc:
        raise RuntimeError(f"torchaudio is not available for acoustic unit extraction: {exc}") from exc
    waveform, sample_rate = torchaudio.load(str(audio_path))
    if hasattr(waveform, "dim") and callable(getattr(waveform, "dim")) and waveform.dim() > 1:
        waveform = waveform.mean(dim=0, keepdim=True)
    if int(sample_rate) != 16000:
        try:
            waveform = torchaudio.functional.resample(waveform, int(sample_rate), 16000)
        except Exception as exc:
            raise RuntimeError(f"torchaudio resampling is not available for acoustic units: {exc}") from exc
        sample_rate = 16000
    return waveform, int(sample_rate)


def _slice_waveform(waveform: Any, sample_rate: int, start: float, end: float) -> Any:
    start_sample = max(0, int(round(float(start) * sample_rate)))
    end_sample = max(start_sample, int(round(float(end) * sample_rate)))
    return waveform[..., start_sample:end_sample]


def _candidate_spans(
    *,
    cut_map: list[dict[str, float]],
    duration_seconds: float,
) -> list[dict[str, float]]:
    if cut_map:
        return cut_map
    if duration_seconds <= 0:
        return []
    return [
        {
            "trimmed_start": 0.0,
            "trimmed_end": duration_seconds,
            "original_start": 0.0,
            "original_end": duration_seconds,
        }
    ]


def _load_tokens(path: Path) -> dict[int, str]:
    rows: dict[int, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.strip().split()
        if not parts:
            continue
        token = parts[0]
        try:
            index = int(parts[1]) if len(parts) > 1 else len(rows)
        except ValueError:
            index = len(rows)
        rows[index] = token
    return rows


def _ctc_greedy_decode(log_probs: Any, vocab: dict[int, str], numpy_module: Any) -> list[str]:
    if len(log_probs.shape) == 3:
        log_probs = log_probs[0]
    predictions = numpy_module.argmax(log_probs, axis=-1)
    decoded: list[str] = []
    previous = -1
    blank_id = 0
    for raw_index in predictions:
        index = int(raw_index)
        if index != blank_id and index != previous:
            token = vocab.get(index, "")
            if token:
                decoded.append(token)
        previous = index
    return decoded


@lru_cache(maxsize=2)
def _load_zipa_model() -> LoadedZipaModel:
    try:
        import numpy as np
        import onnxruntime as ort
        import torch
        from huggingface_hub import hf_hub_download
        from lhotse.features.kaldi.extractors import Fbank, FbankConfig
    except Exception as exc:
        raise RuntimeError(f"ZIPA dependencies are not available: {exc}") from exc

    model_path = Path(
        hf_hub_download(repo_id=ACOUSTIC_UNIT_MODEL_ID, filename=ACOUSTIC_UNIT_MODEL_FILE)
    )
    tokens_path = Path(
        hf_hub_download(repo_id=ACOUSTIC_UNIT_MODEL_ID, filename=ACOUSTIC_UNIT_TOKENS_FILE)
    )
    session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
    extractor = Fbank(FbankConfig(num_filters=80, dither=0.0, snip_edges=False))
    return LoadedZipaModel(
        session=session,
        vocab=_load_tokens(tokens_path),
        extractor=extractor,
        torch_module=torch,
        numpy_module=np,
    )


def _decode_zipa_waveform(waveform: Any, sample_rate: int) -> tuple[str, float | None]:
    loaded = _load_zipa_model()
    if int(sample_rate) != 16000:
        raise RuntimeError("ZIPA acoustic unit extraction requires 16000 Hz audio.")
    if hasattr(waveform, "dim") and waveform.dim() > 1:
        waveform = waveform.squeeze(0)
    features = loaded.extractor.extract_batch([waveform.float()], sampling_rate=16000)
    feature = features[0].unsqueeze(0)
    feature_lens = loaded.numpy_module.array([feature.shape[1]], dtype=loaded.numpy_module.int64)
    outputs = loaded.session.run(
        None,
        {
            "x": feature.numpy(),
            "x_lens": feature_lens,
        },
    )
    log_probs = outputs[0][0]
    tokens = _ctc_greedy_decode(log_probs, loaded.vocab, loaded.numpy_module)
    confidence: float | None = None
    try:
        max_logits = loaded.numpy_module.max(log_probs, axis=-1)
        confidence = float(loaded.numpy_module.mean(max_logits))
    except Exception:
        confidence = None
    return _compact_text(" ".join(tokens)), confidence


def generate_acoustic_unit_turns(
    *,
    audio_path: Any,
    cut_map: list[dict[str, float]],
    compute_mode: str | None = None,
) -> AcousticUnitResult:
    del compute_mode
    warnings: list[str] = []
    try:
        waveform, sample_rate = _load_waveform(audio_path)
        spans = _candidate_spans(
            cut_map=cut_map,
            duration_seconds=_waveform_duration_seconds(waveform, sample_rate),
        )
        turns: list[AcousticUnitTurn] = []
        for index, span in enumerate(spans, start=1):
            trimmed_start = float(span.get("trimmed_start", 0.0) or 0.0)
            trimmed_end = float(span.get("trimmed_end", trimmed_start) or trimmed_start)
            if trimmed_end <= trimmed_start:
                continue
            chunk = _slice_waveform(waveform, sample_rate, trimmed_start, trimmed_end)
            text, confidence = _decode_zipa_waveform(chunk, sample_rate)
            if not text:
                continue
            turns.append(
                AcousticUnitTurn(
                    index=index,
                    start=float(span.get("original_start", trimmed_start) or 0.0),
                    end=float(span.get("original_end", trimmed_end) or trimmed_end),
                    acoustic_units=text,
                    confidence=confidence,
                )
            )
    except Exception as exc:
        return AcousticUnitResult(
            backend_name=ACOUSTIC_UNIT_BACKEND,
            model_id=ACOUSTIC_UNIT_MODEL_ID,
            status="unavailable",
            unit_type=ACOUSTIC_UNIT_TYPE,
            turns=[],
            warnings=[f"Acoustic unit extraction failed: {exc}"],
        )

    if not turns:
        warnings.append("Acoustic unit extraction produced no turns.")
        return AcousticUnitResult(
            backend_name=ACOUSTIC_UNIT_BACKEND,
            model_id=ACOUSTIC_UNIT_MODEL_ID,
            status="unavailable",
            unit_type=ACOUSTIC_UNIT_TYPE,
            turns=[],
            warnings=warnings,
        )
    return AcousticUnitResult(
        backend_name=ACOUSTIC_UNIT_BACKEND,
        model_id=ACOUSTIC_UNIT_MODEL_ID,
        status="ok",
        unit_type=ACOUSTIC_UNIT_TYPE,
        turns=turns,
        warnings=warnings,
    )


def best_speaker_for_interval(
    start: float,
    end: float,
    speaker_turns: list[dict[str, Any]],
) -> str:
    midpoint = start + ((end - start) / 2.0)
    best_speaker = "SPEAKER_00"
    best_overlap = 0.0
    for turn in speaker_turns:
        turn_start = float(turn.get("start", turn.get("original_start", 0.0)) or 0.0)
        turn_end = float(turn.get("end", turn.get("original_end", turn_start)) or turn_start)
        overlap = max(0.0, min(end, turn_end) - max(start, turn_start))
        if overlap > best_overlap:
            best_overlap = overlap
            best_speaker = str(turn.get("speaker") or "SPEAKER_00")
    if best_overlap > 0:
        return best_speaker

    for turn in speaker_turns:
        turn_start = float(turn.get("start", turn.get("original_start", 0.0)) or 0.0)
        turn_end = float(turn.get("end", turn.get("original_end", turn_start)) or turn_start)
        if turn_start <= midpoint <= turn_end:
            return str(turn.get("speaker") or "SPEAKER_00")
    return best_speaker
