from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import re
from typing import Any, Protocol
import unicodedata

_HIRAGANA_START = ord("ぁ")
_HIRAGANA_END = ord("ゖ")
_KATAKANA_OFFSET = ord("ァ") - ord("ぁ")
_KANA_TEXT_RE = re.compile(r"^[A-Za-zぁ-ゖァ-ヺー\s'’-]+$")
_ASCII_WORD_RE = re.compile(r"^[A-Za-z][A-Za-z'’-]*$")
_SIMPLE_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z'’-]*|[ぁ-ゖァ-ヺー]+")
_VOWEL_RE = re.compile(r"[aiɯeo]")
_KANJI_RE = re.compile(r"[一-龯々]")

DEFAULT_IPA_BACKEND = "sudachi-reading-ipa-v1"
EXPERIMENTAL_PYOPENJTALK_IPA_BACKEND = "pyopenjtalk-g2p-v1"
MIXED_DERIVED_IPA_BACKEND = "mixed-derived-ipa-v1"
AUDIO_TO_IPA_BACKEND = "wav2vec2-xlsr-53-espeak-cv-ft-v1"
AUDIO_TO_IPA_MODEL_ID = "facebook/wav2vec2-xlsr-53-espeak-cv-ft"
AUDIO_TO_IPA_UNCONFIGURED_BACKEND = "audio-to-ipa-unconfigured-v1"

_SPECIAL_READINGS = {
    "こんにちは": "コンニチワ",
    "こんばんは": "コンバンワ",
}

_KATAKANA_BASE_IPA = {
    "ア": "a",
    "イ": "i",
    "ウ": "ɯ",
    "エ": "e",
    "オ": "o",
    "カ": "ka",
    "キ": "ki",
    "ク": "kɯ",
    "ケ": "ke",
    "コ": "ko",
    "サ": "sa",
    "シ": "ɕi",
    "ス": "sɯ",
    "セ": "se",
    "ソ": "so",
    "タ": "ta",
    "チ": "tɕi",
    "ツ": "tsɯ",
    "テ": "te",
    "ト": "to",
    "ナ": "na",
    "ニ": "ni",
    "ヌ": "nɯ",
    "ネ": "ne",
    "ノ": "no",
    "ハ": "ha",
    "ヒ": "çi",
    "フ": "ɸɯ",
    "ヘ": "he",
    "ホ": "ho",
    "マ": "ma",
    "ミ": "mi",
    "ム": "mɯ",
    "メ": "me",
    "モ": "mo",
    "ヤ": "ja",
    "ユ": "jɯ",
    "ヨ": "jo",
    "ラ": "ɾa",
    "リ": "ɾi",
    "ル": "ɾɯ",
    "レ": "ɾe",
    "ロ": "ɾo",
    "ワ": "wa",
    "ヲ": "o",
    "ン": "ɴ",
    "ガ": "ga",
    "ギ": "gi",
    "グ": "gɯ",
    "ゲ": "ge",
    "ゴ": "go",
    "ザ": "za",
    "ジ": "dʑi",
    "ズ": "zɯ",
    "ゼ": "ze",
    "ゾ": "zo",
    "ダ": "da",
    "ヂ": "dʑi",
    "ヅ": "zɯ",
    "デ": "de",
    "ド": "do",
    "バ": "ba",
    "ビ": "bi",
    "ブ": "bɯ",
    "ベ": "be",
    "ボ": "bo",
    "パ": "pa",
    "ピ": "pi",
    "プ": "pɯ",
    "ペ": "pe",
    "ポ": "po",
    "ヴ": "vɯ",
    "ァ": "a",
    "ィ": "i",
    "ゥ": "ɯ",
    "ェ": "e",
    "ォ": "o",
    "ャ": "ja",
    "ュ": "jɯ",
    "ョ": "jo",
    "ヮ": "wa",
}

_KATAKANA_COMBINED_IPA = {
    "キャ": "kja",
    "キュ": "kjɯ",
    "キョ": "kjo",
    "ギャ": "gja",
    "ギュ": "gjɯ",
    "ギョ": "gjo",
    "シャ": "ɕa",
    "シュ": "ɕɯ",
    "ショ": "ɕo",
    "ジャ": "dʑa",
    "ジュ": "dʑɯ",
    "ジョ": "dʑo",
    "チャ": "tɕa",
    "チュ": "tɕɯ",
    "チョ": "tɕo",
    "ニャ": "nja",
    "ニュ": "njɯ",
    "ニョ": "njo",
    "ヒャ": "ça",
    "ヒュ": "çɯ",
    "ヒョ": "ço",
    "ビャ": "bja",
    "ビュ": "bjɯ",
    "ビョ": "bjo",
    "ピャ": "pja",
    "ピュ": "pjɯ",
    "ピョ": "pjo",
    "ミャ": "mja",
    "ミュ": "mjɯ",
    "ミョ": "mjo",
    "リャ": "ɾja",
    "リュ": "ɾjɯ",
    "リョ": "ɾjo",
    "ファ": "ɸa",
    "フィ": "fi",
    "フェ": "ɸe",
    "フォ": "ɸo",
    "フュ": "ɸjɯ",
    "ウィ": "wi",
    "ウェ": "we",
    "ウォ": "wo",
    "ヴァ": "va",
    "ヴィ": "vi",
    "ヴェ": "ve",
    "ヴォ": "vo",
    "ヴュ": "vjɯ",
    "ティ": "ti",
    "ディ": "di",
    "トゥ": "tɯ",
    "ドゥ": "dɯ",
    "チェ": "tɕe",
    "シェ": "ɕe",
    "ジェ": "dʑe",
    "スィ": "si",
    "ズィ": "zi",
    "ツァ": "tsa",
    "ツィ": "tsi",
    "ツェ": "tse",
    "ツォ": "tso",
    "クァ": "kwa",
    "クィ": "kwi",
    "クェ": "kwe",
    "クォ": "kwo",
    "グァ": "gwa",
    "グィ": "gwi",
    "グェ": "gwe",
    "グォ": "gwo",
}

_ASCII_DIGRAPHS = {
    "sh": "ʃ",
    "ch": "tʃ",
    "th": "θ",
    "ph": "f",
    "ng": "ŋ",
    "qu": "kw",
    "ck": "k",
}

_ASCII_SINGLE = {
    "a": "a",
    "b": "b",
    "c": "k",
    "d": "d",
    "e": "e",
    "f": "f",
    "g": "g",
    "h": "h",
    "i": "i",
    "j": "dʒ",
    "k": "k",
    "l": "l",
    "m": "m",
    "n": "n",
    "o": "o",
    "p": "p",
    "q": "k",
    "r": "ɹ",
    "s": "s",
    "t": "t",
    "u": "u",
    "v": "v",
    "w": "w",
    "x": "ks",
    "y": "j",
    "z": "z",
}


class SudachiMorpheme(Protocol):
    def surface(self) -> str: ...
    def normalized_form(self) -> str: ...
    def reading_form(self) -> str: ...
    def part_of_speech(self) -> tuple[str, ...] | list[str]: ...


class SudachiTokenizer(Protocol):
    def tokenize(self, text: str) -> list[SudachiMorpheme]: ...


@dataclass
class IPATurn:
    index: int
    start: float
    end: float
    speaker: str
    ipa: str
    confidence: float | None = None


@dataclass
class IPAResult:
    backend_name: str
    status: str
    turns: list[IPATurn]
    warnings: list[str]
    source_type: str = "text_derived"


@dataclass
class LoadedAudioIpaModel:
    model_id: str
    device: str
    processor: Any
    model: Any
    torch_module: Any


@lru_cache(maxsize=1)
def _get_sudachi_tokenizer() -> SudachiTokenizer | None:
    try:
        from sudachipy import Dictionary
    except ImportError:
        return None

    return Dictionary(dict="core").create()


def _get_pyopenjtalk_module() -> Any | None:
    try:
        import pyopenjtalk
    except ImportError:
        return None
    return pyopenjtalk


def _compact_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _to_katakana(text: str) -> str:
    chars: list[str] = []
    for char in text:
        codepoint = ord(char)
        if char == "ゔ":
            chars.append("ヴ")
        elif _HIRAGANA_START <= codepoint <= _HIRAGANA_END:
            chars.append(chr(codepoint + _KATAKANA_OFFSET))
        else:
            chars.append(char)
    return "".join(chars)


def _is_kana(text: str) -> bool:
    normalized = _to_katakana(text)
    return bool(normalized) and all(
        char in _KATAKANA_BASE_IPA or char in {"ッ", "ー"}
        for char in normalized
    )


def _is_ascii_word(text: str) -> bool:
    return bool(_ASCII_WORD_RE.fullmatch(text))


def _contains_kanji(text: str) -> bool:
    return bool(_KANJI_RE.search(text))


def _is_symbol_like(text: str) -> bool:
    compact = str(text or "").strip()
    if not compact:
        return True
    return all(
        unicodedata.category(char).startswith(("P", "S", "Z"))
        for char in compact
    )


def _special_reading(text: str) -> str | None:
    normalized = _compact_text(text)
    return _SPECIAL_READINGS.get(normalized)


def _last_vowel(ipa: str) -> str | None:
    matches = _VOWEL_RE.findall(ipa)
    return matches[-1] if matches else None


def _leading_consonants(ipa: str) -> str:
    match = _VOWEL_RE.search(ipa)
    if match is None:
        return ipa
    return ipa[: match.start()]


def _latin_to_ipa(word: str) -> str:
    token = re.sub(r"[^A-Za-z]", "", str(word or "")).lower()
    if not token:
        return ""

    parts: list[str] = []
    index = 0
    while index < len(token):
        digraph = token[index : index + 2]
        if digraph in _ASCII_DIGRAPHS:
            parts.append(_ASCII_DIGRAPHS[digraph])
            index += 2
            continue

        char = token[index]
        if char == "c" and index + 1 < len(token) and token[index + 1] in {"e", "i", "y"}:
            parts.append("s")
        else:
            parts.append(_ASCII_SINGLE.get(char, char))
        index += 1
    return "".join(parts)


def _katakana_to_ipa(text: str) -> str:
    katakana = _to_katakana(text)
    parts: list[str] = []
    index = 0

    while index < len(katakana):
        char = katakana[index]
        if char.isspace():
            index += 1
            continue
        if char == "ッ":
            if index + 1 < len(katakana):
                next_chunk = katakana[index + 1 : index + 3]
                next_ipa = _KATAKANA_COMBINED_IPA.get(next_chunk)
                if next_ipa is None:
                    next_ipa = _KATAKANA_BASE_IPA.get(katakana[index + 1], "")
                consonants = _leading_consonants(next_ipa)
                if consonants:
                    parts.append(consonants)
            index += 1
            continue
        if char == "ー":
            if parts:
                vowel = _last_vowel("".join(parts))
                if vowel:
                    parts.append(vowel)
            index += 1
            continue

        chunk = katakana[index : index + 2]
        if chunk in _KATAKANA_COMBINED_IPA:
            parts.append(_KATAKANA_COMBINED_IPA[chunk])
            index += 2
            continue

        ipa = _KATAKANA_BASE_IPA.get(char)
        if ipa:
            parts.append(ipa)
        index += 1

    return "".join(parts)


def _phonemize_simple_text(text: str) -> str | None:
    normalized = _compact_text(text)
    if not normalized:
        return None

    special = _special_reading(normalized)
    if special:
        return _katakana_to_ipa(special)

    if not _KANA_TEXT_RE.fullmatch(normalized):
        return None

    tokens = _SIMPLE_TOKEN_RE.findall(normalized)
    ipa_tokens: list[str] = []
    for token in tokens:
        if _is_kana(token):
            ipa_tokens.append(_katakana_to_ipa(token))
            continue
        if _is_ascii_word(token):
            ascii_ipa = _latin_to_ipa(token)
            if ascii_ipa:
                ipa_tokens.append(ascii_ipa)
    if not ipa_tokens:
        return None
    return " ".join(ipa_tokens)


def _adjust_particle_reading(
    *,
    surface: str,
    normalized_form: str,
    reading_form: str,
    pos: tuple[str, ...] | list[str],
) -> str:
    if surface in _SPECIAL_READINGS:
        return _SPECIAL_READINGS[surface]
    if normalized_form in _SPECIAL_READINGS:
        return _SPECIAL_READINGS[normalized_form]
    if (pos[0] if pos else "") != "助詞":
        return reading_form
    if surface == "は":
        return "ワ"
    if surface == "へ":
        return "エ"
    if surface == "を":
        return "オ"
    return reading_form


def _phonemize_with_sudachi(text: str) -> tuple[str | None, list[str]]:
    tokenizer = _get_sudachi_tokenizer()
    if tokenizer is None:
        return None, [
            "IPA derivation requires SudachiPy for turns containing kanji or mixed-script text."
        ]

    ipa_tokens: list[str] = []
    fallback_latin_used = False
    for morpheme in tokenizer.tokenize(text):
        surface = str(morpheme.surface() or "")
        normalized_form = str(morpheme.normalized_form() or "")
        reading_form = str(morpheme.reading_form() or "")
        pos = tuple(morpheme.part_of_speech() or ())

        if _is_symbol_like(surface) or reading_form == "キゴウ":
            continue

        resolved_reading = _adjust_particle_reading(
            surface=surface,
            normalized_form=normalized_form,
            reading_form=reading_form,
            pos=pos,
        )

        if _is_kana(resolved_reading):
            ipa_tokens.append(_katakana_to_ipa(resolved_reading))
            continue

        for candidate in (normalized_form, surface, resolved_reading):
            if _is_kana(candidate):
                ipa_tokens.append(_katakana_to_ipa(candidate))
                break
        else:
            ascii_source = next(
                (candidate for candidate in (normalized_form, surface, resolved_reading) if _is_ascii_word(candidate)),
                None,
            )
            if ascii_source:
                ascii_ipa = _latin_to_ipa(ascii_source)
                if ascii_ipa:
                    ipa_tokens.append(ascii_ipa)
                    fallback_latin_used = True

    if not ipa_tokens:
        return None, [
            "IPA derivation could not resolve any usable readings from the current turn text."
        ]

    warnings: list[str] = []
    if fallback_latin_used:
        warnings.append("Some IPA spans used a simple ASCII fallback for out-of-vocabulary Latin tokens.")
    return " ".join(ipa_tokens), warnings


def resolve_ipa_backend(preferred_backend: str | None = None) -> str:
    normalized = str(preferred_backend or "").strip().lower()
    if normalized in {
        EXPERIMENTAL_PYOPENJTALK_IPA_BACKEND,
        "pyopenjtalk",
        "pyopenjtalk-g2p",
    }:
        return EXPERIMENTAL_PYOPENJTALK_IPA_BACKEND
    return DEFAULT_IPA_BACKEND


def _derive_ipa_from_text_with_current_backend(normalized: str) -> tuple[str | None, list[str]]:
    if any(char.isascii() and char.isalpha() for char in normalized):
        sudachi_ipa, sudachi_warnings = _phonemize_with_sudachi(normalized)
        if sudachi_ipa:
            return sudachi_ipa, sudachi_warnings

    simple_ipa = _phonemize_simple_text(normalized)
    if simple_ipa:
        return simple_ipa, []

    if _contains_kanji(normalized):
        return _phonemize_with_sudachi(normalized)

    return None, ["IPA derivation could not normalize the current turn text."]


def _phonemize_with_pyopenjtalk(text: str) -> tuple[str | None, list[str]]:
    pyopenjtalk_module = _get_pyopenjtalk_module()
    if pyopenjtalk_module is None:
        return None, [
            "PyOpenJTalk is not available for experimental IPA derivation."
        ]

    try:
        kana_text = str(pyopenjtalk_module.g2p(text, kana=True) or "").strip()
    except Exception as exc:
        return None, [f"PyOpenJTalk failed to derive kana readings: {exc}"]

    if not kana_text:
        return None, ["PyOpenJTalk did not return any kana readings for the current turn text."]

    ipa_text = _katakana_to_ipa(kana_text)
    if not ipa_text:
        return None, ["PyOpenJTalk returned kana readings, but IPA conversion produced an empty result."]
    return ipa_text, []


def _derive_ipa_from_text(
    text: str,
    *,
    preferred_backend: str | None = None,
) -> tuple[str | None, list[str], str | None]:
    normalized = _compact_text(text)
    if not normalized:
        return None, [], None

    selected_backend = resolve_ipa_backend(preferred_backend)
    warnings: list[str] = []

    if selected_backend == EXPERIMENTAL_PYOPENJTALK_IPA_BACKEND:
        pyopenjtalk_ipa, pyopenjtalk_warnings = _phonemize_with_pyopenjtalk(normalized)
        warnings.extend(pyopenjtalk_warnings)
        if pyopenjtalk_ipa:
            return pyopenjtalk_ipa, warnings, EXPERIMENTAL_PYOPENJTALK_IPA_BACKEND
        warnings.append("PyOpenJTalk backend fell back to the current Sudachi-based IPA path.")

    current_ipa, current_warnings = _derive_ipa_from_text_with_current_backend(normalized)
    warnings.extend(current_warnings)
    if current_ipa:
        return current_ipa, warnings, DEFAULT_IPA_BACKEND
    return None, warnings, None


def _ensure_slashes(value: str) -> str:
    stripped = str(value or "").strip()
    if not stripped:
        return ""
    if stripped.startswith("/") and stripped.endswith("/"):
        return stripped
    return f"/{stripped}/"


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def generate_ipa_turns(
    *,
    transcript_payload: dict[str, Any],
    preferred_backend: str | None = None,
) -> IPAResult:
    raw_segments = (
        transcript_payload.get("speaker_segments")
        or transcript_payload.get("segments")
        or transcript_payload.get("raw_segments")
        or []
    )
    turns: list[IPATurn] = []
    warnings: list[str] = []
    derived_backends: list[str] = []

    for index, segment in enumerate(raw_segments, start=1):
        ipa_text = str(
            segment.get("ipa")
            or segment.get("ipa_text")
            or segment.get("phonemes")
            or ""
        ).strip()
        if not ipa_text:
            derived_text, derived_warnings, derived_backend = _derive_ipa_from_text(
                segment.get("text"),
                preferred_backend=preferred_backend,
            )
            warnings.extend(derived_warnings)
            ipa_text = derived_text or ""
            if derived_backend and ipa_text:
                derived_backends.append(derived_backend)
        if not ipa_text:
            continue

        turns.append(
            IPATurn(
                index=int(segment.get("index", index) or index),
                start=float(segment.get("original_start", segment.get("start", 0.0)) or 0.0),
                end=float(
                    segment.get("original_end", segment.get("end", segment.get("start", 0.0)))
                    or 0.0
                ),
                speaker=str(segment.get("speaker") or "SPEAKER_00"),
                ipa=_ensure_slashes(ipa_text),
                confidence=_optional_float(segment.get("confidence")),
            )
        )

    deduped_warnings = list(dict.fromkeys(row for row in warnings if str(row).strip()))
    if turns:
        backend_name = "segment-ipa-passthrough"
        if derived_backends:
            unique_backends = list(dict.fromkeys(derived_backends))
            backend_name = (
                unique_backends[0]
                if len(unique_backends) == 1
                else MIXED_DERIVED_IPA_BACKEND
            )
        return IPAResult(
            backend_name=backend_name,
            status="ok",
            turns=turns,
            warnings=deduped_warnings,
            source_type="text_derived",
        )

    return IPAResult(
        backend_name=resolve_ipa_backend(preferred_backend),
        status="unavailable",
        turns=[],
        warnings=deduped_warnings
        or ["IPA turn data is not available from the current transcription payload."],
        source_type="text_derived",
    )


def _best_speaker_for_interval(
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


def align_ipa_turns_to_speakers(
    *,
    ipa_result: IPAResult,
    speaker_payload: dict[str, Any],
) -> IPAResult:
    speaker_turns = list(speaker_payload.get("speaker_turns") or [])
    if not ipa_result.turns or not speaker_turns:
        return ipa_result

    aligned_turns = [
        IPATurn(
            index=turn.index,
            start=turn.start,
            end=turn.end,
            speaker=_best_speaker_for_interval(turn.start, turn.end, speaker_turns),
            ipa=turn.ipa,
            confidence=turn.confidence,
        )
        for turn in ipa_result.turns
    ]
    return IPAResult(
        backend_name=ipa_result.backend_name,
        status=ipa_result.status,
        turns=aligned_turns,
        warnings=ipa_result.warnings,
        source_type=ipa_result.source_type,
    )


def _audio_ipa_device(compute_mode: str | None) -> tuple[str, list[str]]:
    warnings: list[str] = []
    try:
        import torch
    except Exception:
        return "cpu", ["PyTorch is not available; audio-to-IPA cannot use GPU."]

    if str(compute_mode or "").strip().lower() == "gpu":
        cuda = getattr(torch, "cuda", None)
        if callable(getattr(cuda, "is_available", None)) and cuda.is_available():
            return "cuda", warnings
        warnings.append("GPU was requested for audio-to-IPA, but CUDA is not available; using CPU.")
    return "cpu", warnings


@lru_cache(maxsize=2)
def _load_audio_ipa_model(device: str) -> LoadedAudioIpaModel:
    try:
        import torch
        from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor
    except Exception as exc:
        raise RuntimeError(f"audio-to-IPA dependencies are not available: {exc}") from exc

    processor = Wav2Vec2Processor.from_pretrained(AUDIO_TO_IPA_MODEL_ID)
    model = Wav2Vec2ForCTC.from_pretrained(AUDIO_TO_IPA_MODEL_ID)
    model.eval()
    if hasattr(model, "to"):
        model.to(device)
    return LoadedAudioIpaModel(
        model_id=AUDIO_TO_IPA_MODEL_ID,
        device=device,
        processor=processor,
        model=model,
        torch_module=torch,
    )


def _load_audio_ipa_waveform(audio_path: Any) -> tuple[Any, int]:
    try:
        import torchaudio
    except Exception as exc:
        raise RuntimeError(f"torchaudio is not available for audio-to-IPA: {exc}") from exc

    waveform, sample_rate = torchaudio.load(str(audio_path))
    if hasattr(waveform, "dim") and callable(getattr(waveform, "dim")) and waveform.dim() > 1:
        waveform = waveform.mean(dim=0)
    return waveform, int(sample_rate)


def _waveform_duration_seconds(waveform: Any, sample_rate: int) -> float:
    sample_count = int(getattr(waveform, "shape", [0])[-1] or 0)
    if sample_rate <= 0:
        return 0.0
    return sample_count / float(sample_rate)


def _slice_waveform(waveform: Any, sample_rate: int, start: float, end: float) -> Any:
    start_sample = max(0, int(start * sample_rate))
    end_sample = max(start_sample, int(end * sample_rate))
    return waveform[..., start_sample:end_sample]


def _resample_for_audio_ipa(waveform: Any, sample_rate: int) -> tuple[Any, int]:
    if sample_rate == 16000:
        return waveform, sample_rate
    try:
        import torchaudio
    except Exception as exc:
        raise RuntimeError(f"torchaudio resampling is not available for audio-to-IPA: {exc}") from exc
    resampler = torchaudio.transforms.Resample(orig_freq=sample_rate, new_freq=16000)
    return resampler(waveform), 16000


def _waveform_to_float_list(waveform: Any) -> list[float]:
    if hasattr(waveform, "detach"):
        waveform = waveform.detach()
    if hasattr(waveform, "cpu"):
        waveform = waveform.cpu()
    if hasattr(waveform, "numpy"):
        return [float(value) for value in waveform.numpy().reshape(-1).tolist()]
    return [float(value) for value in list(waveform)]


def _decode_audio_ipa_waveform(
    *,
    waveform: Any,
    sample_rate: int,
    compute_mode: str | None,
) -> tuple[str, float | None, str, list[str]]:
    device, warnings = _audio_ipa_device(compute_mode)
    loaded = _load_audio_ipa_model(device)
    waveform, sample_rate = _resample_for_audio_ipa(waveform, sample_rate)
    samples = _waveform_to_float_list(waveform)
    if not samples:
        return "", None, AUDIO_TO_IPA_BACKEND, warnings

    inputs = loaded.processor(
        samples,
        sampling_rate=sample_rate,
        return_tensors="pt",
        padding=True,
    )
    input_values = inputs.input_values
    if hasattr(input_values, "to"):
        input_values = input_values.to(loaded.device)

    with loaded.torch_module.no_grad():
        logits = loaded.model(input_values).logits
        predicted_ids = loaded.torch_module.argmax(logits, dim=-1)
        decoded = loaded.processor.batch_decode(predicted_ids)

    confidence: float | None = None
    try:
        probs = loaded.torch_module.nn.functional.softmax(logits, dim=-1)
        confidence = float(probs.max(dim=-1).values.mean().item())
    except Exception:
        confidence = None

    return _compact_text(decoded[0] if decoded else ""), confidence, AUDIO_TO_IPA_BACKEND, warnings


def _audio_ipa_spans(
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


def generate_audio_ipa_turns(
    *,
    audio_path: Any,
    cut_map: list[dict[str, float]],
    preferred_backend: str | None = None,
    compute_mode: str | None = None,
) -> IPAResult:
    del preferred_backend
    warnings: list[str] = []
    try:
        waveform, sample_rate = _load_audio_ipa_waveform(audio_path)
        spans = _audio_ipa_spans(
            cut_map=cut_map,
            duration_seconds=_waveform_duration_seconds(waveform, sample_rate),
        )
        turns: list[IPATurn] = []
        for index, span in enumerate(spans, start=1):
            trimmed_start = float(span.get("trimmed_start", 0.0) or 0.0)
            trimmed_end = float(span.get("trimmed_end", trimmed_start) or trimmed_start)
            if trimmed_end <= trimmed_start:
                continue
            chunk = _slice_waveform(waveform, sample_rate, trimmed_start, trimmed_end)
            ipa_text, confidence, backend_name, decode_warnings = _decode_audio_ipa_waveform(
                waveform=chunk,
                sample_rate=sample_rate,
                compute_mode=compute_mode,
            )
            warnings.extend(decode_warnings)
            if not ipa_text:
                continue
            turns.append(
                IPATurn(
                    index=index,
                    start=float(span.get("original_start", trimmed_start) or 0.0),
                    end=float(span.get("original_end", trimmed_end) or trimmed_end),
                    speaker="",
                    ipa=_ensure_slashes(ipa_text),
                    confidence=confidence,
                )
            )
    except Exception as exc:
        return IPAResult(
            backend_name=AUDIO_TO_IPA_BACKEND,
            status="unavailable",
            turns=[],
            warnings=[f"Audio-to-IPA failed: {exc}"],
            source_type="audio",
        )

    deduped_warnings = list(dict.fromkeys(row for row in warnings if str(row).strip()))
    if not turns:
        return IPAResult(
            backend_name=AUDIO_TO_IPA_BACKEND,
            status="unavailable",
            turns=[],
            warnings=deduped_warnings or ["Audio-to-IPA produced no IPA turns."],
            source_type="audio",
        )
    return IPAResult(
        backend_name=AUDIO_TO_IPA_BACKEND,
        status="ok",
        turns=turns,
        warnings=deduped_warnings,
        source_type="audio",
    )
