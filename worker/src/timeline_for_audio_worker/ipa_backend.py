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


@dataclass
class IPAResult:
    backend_name: str
    status: str
    turns: list[IPATurn]
    warnings: list[str]


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
        )

    return IPAResult(
        backend_name=resolve_ipa_backend(preferred_backend),
        status="unavailable",
        turns=[],
        warnings=deduped_warnings
        or ["IPA turn data is not available from the current transcription payload."],
    )
