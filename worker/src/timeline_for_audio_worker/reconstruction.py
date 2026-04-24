from __future__ import annotations

from dataclasses import asdict, dataclass
import gc
from pathlib import Path
import re
from typing import Any

from .ipa_backend import IPAResult

_HIRAGANA_START = ord("ぁ")
_HIRAGANA_END = ord("ゖ")
_KATAKANA_OFFSET = ord("ァ") - ord("ぁ")
_ASCII_FRAGMENT_RUN_RE = re.compile(
    r"(?<![A-Za-z0-9])([A-Za-z0-9]{1,4}(?: [A-Za-z0-9]{1,4})+)(?![A-Za-z0-9])"
)
_LANGUAGE_SPLIT_RE = re.compile(r"[,;/\s]+")
_JAPANESE_CHAR_RE = re.compile(r"[ぁ-んァ-ヶ一-龯々ー]")
_TIMESTAMP_TOKEN_RE = re.compile(r"\b\d{2}:\d{2}:\d{2}\.\d{3}\b")
_LOW_DIVERSITY_REPEAT_RE = re.compile(r"(.{2,6})\1{3,}")

LOCAL_LLM_RECONSTRUCTION_BACKEND = "local-transformers-japanese-p2g-v1"
LOCAL_LLM_MODEL_ID = "Respair/Japanese_Phoneme_to_Grapheme_LLM"
LOCAL_LLM_PROMPT_VERSION = "ipa-turn-reconstruction-ja-v3"
LOCAL_LLM_MAX_NEW_TOKENS = 128
LOCAL_LLM_REPETITION_PENALTY = 1.02
FALLBACK_RECONSTRUCTION_BACKEND = "ipa-aligned-text-fallback-v1"
SEGMENT_FALLBACK_RECONSTRUCTION_BACKEND = "segment-text-fallback-v1"
_GENERIC_INVALID_RECONSTRUCTION_PHRASES = (
    "the quick brown fox",
    "the speaker is",
    "the speaker is speaking",
    "the time is",
    "timeanddateofthespeech",
    "thetimeis",
    "thisisagood thing",
    "ipa:",
)


@dataclass
class LoadedLocalLlm:
    model_id: str
    requested_compute_mode: str
    effective_device: str
    tokenizer: Any
    model: Any
    torch_module: Any


_LOCAL_LLM_CACHE: dict[tuple[str, str], LoadedLocalLlm] = {}


@dataclass
class ReconstructedTurn:
    index: int
    start: float
    end: float
    speaker: str
    text: str


@dataclass
class ReconstructionResult:
    backend_name: str
    status: str
    turns: list[ReconstructedTurn]
    warnings: list[str]
    model_id: str | None = None
    prompt_version: str | None = None
    requested_compute_mode: str | None = None
    effective_device: str | None = None
    decoding: dict[str, Any] | None = None

    def to_metadata_dict(self) -> dict[str, Any]:
        return asdict(self)


def _compact_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _normalize_multiline_text(value: str | None) -> str:
    if value is None:
        return ""
    normalized = str(value).replace("\r\n", "\n").replace("\r", "\n")
    normalized = "\n".join(line.rstrip() for line in normalized.split("\n")).strip()
    return normalized


def _normalize_source_name_hint(value: str | None) -> str:
    normalized = _normalize_multiline_text(value)
    if not normalized:
        return ""
    stem = _normalize_multiline_text(Path(normalized).stem)
    return stem or normalized


def _normalize_language_tags(value: str | None) -> list[str]:
    normalized = _normalize_multiline_text(value).lower()
    if not normalized:
        return []
    return [part for part in _LANGUAGE_SPLIT_RE.split(normalized) if part]


def _language_hint_supports_local_llm(language_hint: str | None) -> bool:
    tags = _normalize_language_tags(language_hint)
    if not tags:
        return True
    return any(tag == "ja" or tag.startswith("ja-") for tag in tags)


def resolve_reconstruction_backend(
    language_hint: str | None,
    compute_mode: str | None = None,
) -> str:
    normalized_compute_mode = str(compute_mode or "cpu").strip().lower()
    return (
        LOCAL_LLM_RECONSTRUCTION_BACKEND
        if normalized_compute_mode == "gpu" and _language_hint_supports_local_llm(language_hint)
        else FALLBACK_RECONSTRUCTION_BACKEND
    )


def resolve_reconstruction_model_id(
    language_hint: str | None,
    compute_mode: str | None = None,
) -> str | None:
    if (
        resolve_reconstruction_backend(language_hint, compute_mode)
        != LOCAL_LLM_RECONSTRUCTION_BACKEND
    ):
        return None
    return LOCAL_LLM_MODEL_ID


def resolve_reconstruction_prompt_version(
    language_hint: str | None,
    compute_mode: str | None = None,
) -> str | None:
    if (
        resolve_reconstruction_backend(language_hint, compute_mode)
        != LOCAL_LLM_RECONSTRUCTION_BACKEND
    ):
        return None
    return LOCAL_LLM_PROMPT_VERSION


def build_reconstruction_decoding(
    language_hint: str | None,
    compute_mode: str | None = None,
) -> dict[str, Any] | None:
    if (
        resolve_reconstruction_backend(language_hint, compute_mode)
        != LOCAL_LLM_RECONSTRUCTION_BACKEND
    ):
        return None
    return {
        "do_sample": False,
        "max_new_tokens": LOCAL_LLM_MAX_NEW_TOKENS,
        "repetition_penalty": LOCAL_LLM_REPETITION_PENALTY,
    }


def _katakana_to_hiragana(text: str) -> str:
    chars: list[str] = []
    for char in str(text or ""):
        codepoint = ord(char)
        if char == "ヴ":
            chars.append("ゔ")
        elif ord("ァ") <= codepoint <= ord("ヶ"):
            chars.append(chr(codepoint - _KATAKANA_OFFSET))
        else:
            chars.append(char)
    return "".join(chars)


def _join_ascii_fragment_run(match: re.Match[str]) -> str:
    tokens = match.group(1).split()
    if not tokens:
        return ""
    if not any(len(token) <= 2 or any(char.isdigit() for char in token) for token in tokens):
        return match.group(1)
    if all(len(token) == 1 for token in tokens):
        return "".join(token.upper() if token.isalpha() else token for token in tokens)
    return "".join(tokens)


def _cleanup_readable_text(text: str) -> tuple[str, bool]:
    compact = _compact_text(text)
    if not compact:
        return "", False

    cleaned = _ASCII_FRAGMENT_RUN_RE.sub(_join_ascii_fragment_run, compact)
    cleaned = re.sub(r"\s+([、。，．！？!?:;])", r"\1", cleaned)
    cleaned = re.sub(r"([(\[（])\s+", r"\1", cleaned)
    cleaned = re.sub(r"\s+([)\]）])", r"\1", cleaned)
    return cleaned, cleaned != compact


def _sanitize_llm_text(text: str) -> tuple[str, bool]:
    normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    normalized = normalized.strip("`").strip()
    normalized = re.sub(r"^(text|transcript|output)\s*[:：]\s*", "", normalized, flags=re.IGNORECASE)
    normalized = " ".join(line.strip() for line in normalized.splitlines() if line.strip())
    return _cleanup_readable_text(normalized)


def _looks_like_invalid_reconstruction(
    text: str,
    *,
    segment_text: str | None = None,
    language_hint: str | None = None,
) -> bool:
    compact = _compact_text(text)
    if not compact:
        return True

    lowered = compact.lower()
    if any(phrase in lowered for phrase in _GENERIC_INVALID_RECONSTRUCTION_PHRASES):
        return True

    japanese_count = len(_JAPANESE_CHAR_RE.findall(compact))
    ascii_letter_count = sum(1 for char in compact if char.isascii() and char.isalpha())
    if japanese_count == 0 and ascii_letter_count >= 8:
        return True

    if _TIMESTAMP_TOKEN_RE.search(compact):
        return True

    compact_no_space = compact.replace(" ", "")
    if _LOW_DIVERSITY_REPEAT_RE.search(compact_no_space):
        return True
    if len(compact_no_space) >= 48:
        unique_chars = len(set(compact_no_space))
        if unique_chars * 6 < len(compact_no_space):
            return True

    if _language_hint_supports_local_llm(language_hint):
        segment_compact = _compact_text(segment_text)
        segment_japanese_count = len(_JAPANESE_CHAR_RE.findall(segment_compact))
        if segment_japanese_count >= 4 and japanese_count == 0:
            return True
        if segment_japanese_count >= 8 and japanese_count * 3 < segment_japanese_count:
            return True
        if ascii_letter_count >= max(12, japanese_count * 2) and japanese_count < 8:
            return True

    return False


def _sorted_segments(transcript_payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_segments = (
        transcript_payload.get("speaker_segments")
        or transcript_payload.get("segments")
        or transcript_payload.get("raw_segments")
        or []
    )
    indexed_segments = list(enumerate(raw_segments))
    indexed_segments.sort(
        key=lambda row: (
            float(row[1].get("original_start", row[1].get("start", 0.0)) or 0.0),
            row[0],
        )
    )
    return [segment for _, segment in indexed_segments]


def _segment_key(segment: dict[str, Any], fallback_index: int) -> tuple[int, int]:
    start_ms = int(round(float(segment.get("original_start", segment.get("start", 0.0)) or 0.0) * 1000))
    return int(segment.get("index", fallback_index) or fallback_index), start_ms


def _match_segment(
    *,
    ipa_turn: Any,
    segment_rows: list[dict[str, Any]],
    segment_index: dict[tuple[int, int], dict[str, Any]],
) -> dict[str, Any] | None:
    exact_key = (int(ipa_turn.index or 0), int(round(float(ipa_turn.start or 0.0) * 1000)))
    exact = segment_index.get(exact_key)
    if exact is not None:
        return exact

    for fallback_index, segment in enumerate(segment_rows, start=1):
        if int(segment.get("index", fallback_index) or fallback_index) != int(ipa_turn.index or 0):
            continue
        return segment
    return None


def _timestamp_label(seconds: float) -> str:
    total_ms = max(0, int(round(seconds * 1000)))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02}.{millis:03}"


def _clear_torch_memory(torch_module: Any) -> None:
    gc.collect()
    cuda = getattr(torch_module, "cuda", None)
    is_available = getattr(cuda, "is_available", None)
    empty_cache = getattr(cuda, "empty_cache", None)
    if callable(is_available) and is_available() and callable(empty_cache):
        empty_cache()


def _is_cuda_oom(exc: Exception) -> bool:
    message = str(exc or "").lower()
    return "out of memory" in message or "cuda failed with error out of memory" in message


def _resolve_requested_device(compute_mode: str | None, torch_module: Any) -> str:
    normalized_compute_mode = str(compute_mode or "cpu").strip().lower()
    if normalized_compute_mode == "gpu":
        cuda = getattr(torch_module, "cuda", None)
        if cuda is not None and callable(getattr(cuda, "is_available", None)) and cuda.is_available():
            return "cuda"
    return "cpu"


def _load_local_llm_backend(
    *,
    model_id: str,
    compute_mode: str | None,
) -> LoadedLocalLlm:
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    requested_device = _resolve_requested_device(compute_mode, torch)
    cache_key = (model_id, requested_device)
    cached = _LOCAL_LLM_CACHE.get(cache_key)
    if cached is not None:
        return cached

    tokenizer = AutoTokenizer.from_pretrained(model_id)
    if tokenizer.pad_token is None and tokenizer.eos_token is not None:
        tokenizer.pad_token = tokenizer.eos_token
    if tokenizer.bos_token is None and tokenizer.pad_token is not None:
        tokenizer.bos_token = tokenizer.pad_token

    model_kwargs: dict[str, Any] = {}
    if requested_device == "cuda":
        model_kwargs["torch_dtype"] = torch.float16

    try:
        model = AutoModelForCausalLM.from_pretrained(model_id, **model_kwargs)
        model.to(requested_device)
        effective_device = requested_device
    except Exception as exc:
        if requested_device != "cuda" or not _is_cuda_oom(exc):
            raise
        _clear_torch_memory(torch)
        model = AutoModelForCausalLM.from_pretrained(model_id)
        model.to("cpu")
        effective_device = "cpu"

    model.eval()
    loaded = LoadedLocalLlm(
        model_id=model_id,
        requested_compute_mode=str(compute_mode or "cpu").strip().lower() or "cpu",
        effective_device=effective_device,
        tokenizer=tokenizer,
        model=model,
        torch_module=torch,
    )
    _LOCAL_LLM_CACHE[cache_key] = loaded
    return loaded


def _build_turn_prompt(
    *,
    turn: Any,
    language_hint: str | None,
    supplemental_context_text: str | None,
    source_name: str | None,
) -> str:
    ipa_text = _normalize_multiline_text(str(turn.ipa or "")).strip().strip("/")
    sections = [f"convert this pronunciation back to normal japanese: {ipa_text}"]
    source_name_hint = _normalize_source_name_hint(source_name)
    if source_name_hint:
        sections.append(f"source file name hint: {source_name_hint[:160]}")
    supplemental_context = _normalize_multiline_text(supplemental_context_text)
    if supplemental_context:
        sections.append(f"known context: {supplemental_context[:240]}")
    if language_hint:
        sections.append(f"language hint: {language_hint}")
    return "\n".join(sections).strip()


def _tokenizer_input_to_device(tokenized: Any, device: str) -> dict[str, Any]:
    if hasattr(tokenized, "items"):
        return {
            name: value.to(device) if hasattr(value, "to") else value
            for name, value in tokenized.items()
        }
    raise TypeError("Tokenizer output is not a mapping.")


def _render_chat_prompt(tokenizer: Any, prompt: str) -> str:
    apply_chat_template = getattr(tokenizer, "apply_chat_template", None)
    if callable(apply_chat_template):
        return apply_chat_template(
            [{"role": "user", "content": prompt}],
            tokenize=False,
            add_generation_prompt=True,
        )
    return prompt


def _generate_turn_text_with_local_llm(
    *,
    loaded_backend: LoadedLocalLlm,
    turn: Any,
    language_hint: str | None,
    supplemental_context_text: str | None,
    source_name: str | None,
) -> tuple[str, bool]:
    tokenizer = loaded_backend.tokenizer
    model = loaded_backend.model
    torch_module = loaded_backend.torch_module
    prompt = _build_turn_prompt(
        turn=turn,
        language_hint=language_hint,
        supplemental_context_text=supplemental_context_text,
        source_name=source_name,
    )
    rendered_prompt = _render_chat_prompt(tokenizer, prompt)
    tokenized = tokenizer([rendered_prompt], return_tensors="pt")
    model_inputs = _tokenizer_input_to_device(tokenized, loaded_backend.effective_device)
    input_ids = model_inputs["input_ids"]
    max_new_tokens = max(48, min(LOCAL_LLM_MAX_NEW_TOKENS, max(48, len(str(turn.ipa or "")) * 2)))
    generate_kwargs = {
        "do_sample": False,
        "max_new_tokens": max_new_tokens,
        "repetition_penalty": LOCAL_LLM_REPETITION_PENALTY,
    }
    pad_token_id = getattr(tokenizer, "pad_token_id", None)
    bos_token_id = getattr(tokenizer, "bos_token_id", None)
    eos_token_id = getattr(tokenizer, "eos_token_id", None)
    if pad_token_id is not None:
        generate_kwargs["pad_token_id"] = pad_token_id
    if bos_token_id is not None:
        generate_kwargs["bos_token_id"] = bos_token_id
    if eos_token_id is not None:
        generate_kwargs["eos_token_id"] = eos_token_id

    with torch_module.no_grad():
        generated = model.generate(**model_inputs, **generate_kwargs)

    generated_ids = generated[:, input_ids.shape[1] :]
    response = tokenizer.batch_decode(generated_ids, skip_special_tokens=True)[0]
    return _sanitize_llm_text(response)


def _fallback_turn_text(segment: dict[str, Any] | None) -> tuple[str, bool]:
    if segment is None:
        return "", False

    text, changed = _cleanup_readable_text(str(segment.get("text") or ""))
    if text:
        return text, changed

    reading_candidates = [
        str(segment.get("reading") or "").strip(),
        str(segment.get("reading_form") or "").strip(),
    ]
    reading_text = next((value for value in reading_candidates if value), "")
    if not reading_text:
        return "", False
    return _cleanup_readable_text(_katakana_to_hiragana(reading_text))


def _prefer_direct_segment_text(
    segment: dict[str, Any] | None,
    *,
    language_hint: str | None,
) -> tuple[str, bool]:
    if segment is None:
        return "", False

    text, changed = _cleanup_readable_text(str(segment.get("text") or ""))
    if not text or not _language_hint_supports_local_llm(language_hint):
        return "", False

    japanese_count = len(_JAPANESE_CHAR_RE.findall(text))
    ascii_letter_count = sum(1 for char in text if char.isascii() and char.isalpha())
    non_ascii_letter_count = sum(1 for char in text if char.isalpha() and not char.isascii())

    if japanese_count > 0 and ascii_letter_count <= max(10, japanese_count * 2):
        return text, changed
    if japanese_count == 0 and ascii_letter_count == 0 and non_ascii_letter_count > 0:
        return text, changed
    return "", False


def _reconstruct_with_local_llm(
    *,
    transcript_payload: dict[str, Any],
    ipa_result: IPAResult,
    language_hint: str | None,
    supplemental_context_text: str | None,
    compute_mode: str | None,
) -> ReconstructionResult:
    segment_rows = _sorted_segments(transcript_payload)
    segment_index = {
        _segment_key(segment, index): segment for index, segment in enumerate(segment_rows, start=1)
    }
    loaded_backend: LoadedLocalLlm | None = None
    turns: list[ReconstructedTurn] = []
    warnings: list[str] = []
    cleanup_changed = False
    fallback_turns = 0
    suspicious_llm_turns = 0
    direct_segment_turns = 0
    requested_compute_mode = str(compute_mode or "cpu").strip().lower() or "cpu"
    source_name = _normalize_multiline_text(str(transcript_payload.get("source_name") or ""))

    for turn in ipa_result.turns:
        segment = _match_segment(
            ipa_turn=turn,
            segment_rows=segment_rows,
            segment_index=segment_index,
        )
        text = ""
        changed = False
        text, changed = _prefer_direct_segment_text(segment, language_hint=language_hint)
        if text:
            direct_segment_turns += 1
        else:
            if loaded_backend is None:
                loaded_backend = _load_local_llm_backend(
                    model_id=LOCAL_LLM_MODEL_ID,
                    compute_mode=compute_mode,
                )
            try:
                text, changed = _generate_turn_text_with_local_llm(
                    loaded_backend=loaded_backend,
                    turn=turn,
                    language_hint=language_hint,
                    supplemental_context_text=supplemental_context_text,
                    source_name=source_name,
                )
            except Exception:
                raise

        if text and _looks_like_invalid_reconstruction(
            text,
            segment_text=str(segment.get("text") or "") if segment is not None else None,
            language_hint=language_hint,
        ):
            text = ""
            suspicious_llm_turns += 1

        if not text:
            text, changed = _fallback_turn_text(segment)
            if text:
                fallback_turns += 1

        if not text:
            continue

        cleanup_changed = cleanup_changed or changed
        turns.append(
            ReconstructedTurn(
                index=int(turn.index),
                start=float(turn.start),
                end=float(turn.end),
                speaker=str(turn.speaker or "SPEAKER_00"),
                text=text,
            )
        )

    if cleanup_changed:
        warnings.append("Readable text cleanup merged fragmented short ASCII token runs in some turns.")
    if fallback_turns:
        warnings.append(
            "Local LLM returned empty text for some turns, so deterministic aligned-text fallback was used."
        )
    if suspicious_llm_turns:
        warnings.append(
            "Local LLM returned prompt leakage or low-fidelity text for some turns, so deterministic aligned-text fallback was used."
        )
    if direct_segment_turns:
        warnings.append("Reliable aligned text was preserved directly for some turns.")
    if loaded_backend is not None:
        requested_device = "cuda" if loaded_backend.requested_compute_mode == "gpu" else "cpu"
        if loaded_backend.effective_device != requested_device:
            warnings.append(
                f"Local LLM reconstruction used `{loaded_backend.effective_device}` because the requested compute path was unavailable."
            )

    if turns:
        return ReconstructionResult(
            backend_name=LOCAL_LLM_RECONSTRUCTION_BACKEND,
            status="ok",
            turns=turns,
            warnings=warnings,
            model_id=LOCAL_LLM_MODEL_ID,
            prompt_version=LOCAL_LLM_PROMPT_VERSION,
            requested_compute_mode=requested_compute_mode,
            effective_device=loaded_backend.effective_device if loaded_backend is not None else None,
            decoding=build_reconstruction_decoding(
                language_hint,
                requested_compute_mode,
            ),
        )

    if loaded_backend is not None:
        warnings.append(
            f"Local LLM reconstruction used `{loaded_backend.effective_device}` because the requested compute path was unavailable."
        )

    return ReconstructionResult(
        backend_name=LOCAL_LLM_RECONSTRUCTION_BACKEND,
        status="unavailable",
        turns=[],
        warnings=warnings or ["Local LLM reconstruction could not produce any non-empty turns."],
        model_id=LOCAL_LLM_MODEL_ID,
        prompt_version=LOCAL_LLM_PROMPT_VERSION,
        requested_compute_mode=requested_compute_mode,
        effective_device=loaded_backend.effective_device if loaded_backend is not None else None,
        decoding=build_reconstruction_decoding(
            language_hint,
            requested_compute_mode,
        ),
    )


def _reconstruct_with_deterministic_fallback(
    *,
    transcript_payload: dict[str, Any],
    ipa_result: IPAResult,
) -> ReconstructionResult:
    segment_rows = _sorted_segments(transcript_payload)
    segment_index = {
        _segment_key(segment, index): segment for index, segment in enumerate(segment_rows, start=1)
    }
    turns: list[ReconstructedTurn] = []
    warnings: list[str] = []
    cleanup_changed = False
    reading_fallback_used = False

    if ipa_result.turns:
        for turn in ipa_result.turns:
            segment = _match_segment(
                ipa_turn=turn,
                segment_rows=segment_rows,
                segment_index=segment_index,
            )
            text, changed = _fallback_turn_text(segment)
            if text and segment is not None and not str(segment.get("text") or "").strip():
                reading_fallback_used = True

            if not text:
                continue

            cleanup_changed = cleanup_changed or changed
            turns.append(
                ReconstructedTurn(
                    index=int(turn.index),
                    start=float(turn.start),
                    end=float(turn.end),
                    speaker=str(turn.speaker or "SPEAKER_00"),
                    text=text,
                )
            )
    else:
        for index, segment in enumerate(segment_rows, start=1):
            text, changed = _cleanup_readable_text(str(segment.get("text") or ""))
            if not text:
                continue
            cleanup_changed = cleanup_changed or changed
            start = float(segment.get("original_start", segment.get("start", 0.0)) or 0.0)
            end = float(segment.get("original_end", segment.get("end", start)) or start)
            turns.append(
                ReconstructedTurn(
                    index=int(segment.get("index", index) or index),
                    start=start,
                    end=end,
                    speaker=str(segment.get("speaker") or "SPEAKER_00"),
                    text=text,
                )
            )

    if cleanup_changed:
        warnings.append("Readable text cleanup merged fragmented short ASCII token runs in some turns.")
    if reading_fallback_used:
        warnings.append("Readable text used kana reading fallbacks for turns without usable aligned text.")

    if turns:
        return ReconstructionResult(
            backend_name=(
                FALLBACK_RECONSTRUCTION_BACKEND
                if ipa_result.turns
                else SEGMENT_FALLBACK_RECONSTRUCTION_BACKEND
            ),
            status="ok",
            turns=turns,
            warnings=warnings,
        )

    return ReconstructionResult(
        backend_name=(
            FALLBACK_RECONSTRUCTION_BACKEND
            if ipa_result.turns
            else SEGMENT_FALLBACK_RECONSTRUCTION_BACKEND
        ),
        status="unavailable",
        turns=[],
        warnings=warnings
        or ["Readable text reconstruction could not produce any non-empty turns."],
    )


def reconstruct_readable_text(
    *,
    transcript_payload: dict[str, Any],
    ipa_result: IPAResult,
    language_hint: str | None = None,
    supplemental_context_text: str | None = None,
    compute_mode: str | None = None,
) -> ReconstructionResult:
    if (
        ipa_result.turns
        and resolve_reconstruction_backend(language_hint, compute_mode)
        == LOCAL_LLM_RECONSTRUCTION_BACKEND
    ):
        return _reconstruct_with_local_llm(
            transcript_payload=transcript_payload,
            ipa_result=ipa_result,
            language_hint=language_hint,
            supplemental_context_text=supplemental_context_text,
            compute_mode=compute_mode,
        )

    return _reconstruct_with_deterministic_fallback(
        transcript_payload=transcript_payload,
        ipa_result=ipa_result,
    )
