from __future__ import annotations

import json
from html import escape
from pathlib import Path
import re
from typing import Any
from urllib.parse import quote

from .fs_utils import write_json_atomic, write_text
from .ipa_backend import _get_sudachi_tokenizer, generate_ipa_turns

_JAPANESE_RE = re.compile(r"[ぁ-んァ-ヶ一-龯々ー]")
_MEANINGFUL_TOKEN_RE = re.compile(r"[A-Za-z0-9ぁ-んァ-ヶ一-龯々ー]")
_JAPANESE_PHRASE_RE = re.compile(r"[A-Za-z0-9ぁ-んァ-ヶ一-龯々ー]+")


def _timestamp_label(seconds: float) -> str:
    total_ms = max(0, int(round(seconds * 1000)))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02}.{millis:03}"


def _compact_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _source_file_name(source_info: dict[str, Any]) -> str:
    for key in ("display_name", "original_path", "audio_id"):
        text = str(source_info.get(key) or "").strip()
        if not text:
            continue
        normalized = text.replace("\\", "/").rstrip("/")
        name = normalized.rsplit("/", 1)[-1].strip()
        if name:
            return name
    return "audio"


def _word_source_rows(transcript_payload: dict[str, Any]) -> list[dict[str, Any]]:
    segment_rows = _japanese_morpheme_rows(transcript_payload)
    if segment_rows:
        return segment_rows

    words = transcript_payload.get("words") or []
    rows: list[dict[str, Any]] = []
    if isinstance(words, list):
        for index, word in enumerate(words, start=1):
            text = _compact_text(word.get("text") if isinstance(word, dict) else "")
            if not text:
                continue
            start = float(word.get("original_start", word.get("start", 0.0)) or 0.0)
            end = float(word.get("original_end", word.get("end", start)) or start)
            rows.append(
                {
                    "index": int(word.get("index", index) or index),
                    "start": start,
                    "end": max(start, end),
                    "speaker": str(word.get("speaker") or "SPEAKER_00"),
                    "text": text,
                    "speaker_overlap_ratio": word.get("speaker_overlap_ratio"),
                }
            )
    if rows:
        return rows

    segments = transcript_payload.get("segments") or transcript_payload.get("speaker_segments") or []
    if not isinstance(segments, list):
        return []
    for index, segment in enumerate(segments, start=1):
        if not isinstance(segment, dict):
            continue
        text = _compact_text(segment.get("text"))
        if not text:
            continue
        start = float(segment.get("original_start", segment.get("start", 0.0)) or 0.0)
        end = float(segment.get("original_end", segment.get("end", start)) or start)
        rows.append(
            {
                "index": index,
                "start": start,
                "end": max(start, end),
                "speaker": str(segment.get("speaker") or "SPEAKER_00"),
                "text": text,
                "speaker_overlap_ratio": segment.get("speaker_overlap_ratio"),
            }
        )
    return rows


def _japanese_morpheme_rows(transcript_payload: dict[str, Any]) -> list[dict[str, Any]]:
    segments = transcript_payload.get("segments") or transcript_payload.get("speaker_segments") or []
    if not isinstance(segments, list):
        return []
    if not any(_JAPANESE_RE.search(str(segment.get("text") or "")) for segment in segments if isinstance(segment, dict)):
        return []

    tokenizer = _get_sudachi_tokenizer()

    rows: list[dict[str, Any]] = []
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        text = _compact_text(segment.get("text"))
        if not text:
            continue
        start = float(segment.get("original_start", segment.get("start", 0.0)) or 0.0)
        end = float(segment.get("original_end", segment.get("end", start)) or start)
        duration = max(0.001, end - start)
        timing_source = "morpheme_approximation"
        if tokenizer is None:
            morphemes = _JAPANESE_PHRASE_RE.findall(text)
            timing_source = "phrase_approximation"
        else:
            morphemes = [
                morpheme.surface()
                for morpheme in tokenizer.tokenize(text)
                if _MEANINGFUL_TOKEN_RE.search(str(morpheme.surface() or ""))
            ]
        if not morphemes:
            continue
        total_chars = sum(max(1, len(token)) for token in morphemes)
        cursor = 0
        for token in morphemes:
            token_len = max(1, len(token))
            token_start = start + (duration * (cursor / total_chars))
            cursor += token_len
            token_end = start + (duration * (cursor / total_chars))
            rows.append(
                {
                    "index": len(rows) + 1,
                    "start": token_start,
                    "end": max(token_start, token_end),
                    "speaker": str(segment.get("speaker") or "SPEAKER_00"),
                    "text": token,
                    "speaker_overlap_ratio": segment.get("speaker_overlap_ratio"),
                    "timing_source": timing_source,
                }
            )
    return rows


def _word_ipa(row: dict[str, Any], preferred_backend: str | None) -> str:
    result = generate_ipa_turns(
        transcript_payload={
            "segments": [
                {
                    "index": 1,
                    "original_start": row["start"],
                    "original_end": row["end"],
                    "speaker": row["speaker"],
                    "text": row["text"],
                }
            ]
        },
        preferred_backend=preferred_backend,
    )
    if not result.turns:
        return ""
    return result.turns[0].ipa


def build_review_data(
    *,
    source_info: dict[str, Any],
    transcript_payload: dict[str, Any],
    ipa_turns: list[dict[str, Any]],
    preferred_backend: str | None = None,
    speaker_count: int | None = None,
) -> dict[str, Any]:
    word_rows = _word_source_rows(transcript_payload)
    words: list[dict[str, Any]] = []
    for index, row in enumerate(word_rows, start=1):
        words.append(
            {
                "index": index,
                "start": round(float(row["start"]), 3),
                "end": round(float(row["end"]), 3),
                "speaker": row["speaker"],
                "text": row["text"],
                "ipa": _word_ipa(row, preferred_backend),
                "speaker_overlap_ratio": row.get("speaker_overlap_ratio"),
                "timing_source": row.get("timing_source", "word_timestamp"),
            }
        )

    duration_candidates = [
        source_info.get("duration_seconds"),
        max((float(turn.get("end", 0.0) or 0.0) for turn in ipa_turns), default=0.0),
        max((float(word.get("end", 0.0) or 0.0) for word in words), default=0.0),
    ]
    duration = max(float(value or 0.0) for value in duration_candidates)

    return {
        "schema_version": 1,
        "title": "TimelineForAudio IPA Review",
        "source_file": _source_file_name(source_info),
        "duration_seconds": round(duration, 3),
        "language_hint": str(source_info.get("language_hint") or "und").strip() or "und",
        "speaker_count": speaker_count,
        "note": "Select the matching local audio file in this page. Audio is not embedded.",
        "turns": ipa_turns,
        "words": words,
    }


def render_review_html(*, output_path: Path, review_data: dict[str, Any]) -> str:
    data_json = json.dumps(review_data, ensure_ascii=False)
    source_file = str(review_data.get("source_file") or "audio")
    rendered = f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>IPA Review - {source_file}</title>
  <style>
    :root {{
      color-scheme: light dark;
      --bg: #0f172a;
      --panel: #111827;
      --panel-soft: #1f2937;
      --text: #e5e7eb;
      --muted: #94a3b8;
      --line: #334155;
      --accent: #38bdf8;
      --current: #facc15;
      --speaker-0: #60a5fa;
      --speaker-1: #f472b6;
      --speaker-2: #34d399;
      --speaker-3: #fbbf24;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--text);
      background: radial-gradient(circle at top left, #1e3a8a 0, transparent 32rem), var(--bg);
    }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 24px; }}
    header {{ display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; margin-bottom: 18px; }}
    h1 {{ margin: 0 0 8px; font-size: clamp(28px, 4vw, 48px); letter-spacing: -0.04em; }}
    .muted {{ color: var(--muted); }}
    .panel {{
      border: 1px solid var(--line);
      background: color-mix(in srgb, var(--panel) 88%, transparent);
      border-radius: 22px;
      padding: 18px;
      box-shadow: 0 20px 60px rgba(0,0,0,.28);
    }}
    .player {{ display: grid; grid-template-columns: 1fr; gap: 14px; margin-bottom: 18px; }}
    audio {{ width: 100%; }}
    input[type=file] {{ width: 100%; padding: 10px; border: 1px dashed var(--line); border-radius: 14px; color: var(--text); }}
    .now {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }}
    .metric {{ background: var(--panel-soft); border-radius: 16px; padding: 14px; min-height: 92px; }}
    .metric small {{ display: block; color: var(--muted); margin-bottom: 6px; }}
    .metric strong {{ font-size: 22px; overflow-wrap: anywhere; }}
    .current-word {{ color: var(--current); }}
    .layout {{ display: grid; grid-template-columns: minmax(0, 1.2fr) minmax(320px, .8fr); gap: 18px; align-items: start; }}
    .words {{ display: flex; flex-wrap: wrap; gap: 8px; align-content: flex-start; max-height: 62vh; overflow: auto; }}
    .word {{
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 8px 10px;
      cursor: pointer;
      background: rgba(15,23,42,.48);
      transition: transform .12s ease, border-color .12s ease, background .12s ease;
    }}
    .word:hover {{ transform: translateY(-1px); border-color: var(--accent); }}
    .word.active {{ background: rgba(250,204,21,.2); border-color: var(--current); color: #fef3c7; }}
    .word .ipa-token {{ display: block; font-size: 14px; font-weight: 800; }}
    .turns {{ display: grid; gap: 10px; max-height: 62vh; overflow: auto; }}
    .turn {{ border: 1px solid var(--line); border-radius: 16px; padding: 12px; background: rgba(15,23,42,.45); cursor: pointer; }}
    .turn.active {{ border-color: var(--current); background: rgba(250,204,21,.12); }}
    .time {{ font-variant-numeric: tabular-nums; color: var(--muted); }}
    .speaker {{ font-weight: 800; }}
    .speaker-0 {{ color: var(--speaker-0); }}
    .speaker-1 {{ color: var(--speaker-1); }}
    .speaker-2 {{ color: var(--speaker-2); }}
    .speaker-3 {{ color: var(--speaker-3); }}
    @media (max-width: 900px) {{
      main {{ padding: 14px; }}
      header, .layout, .now {{ grid-template-columns: 1fr; display: grid; }}
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <h1>IPA Review</h1>
        <div class="muted">Source: <code id="sourceName"></code></div>
      </div>
      <div class="muted">Audio is selected locally. It is not embedded in this file.</div>
    </header>

    <section class="panel player">
      <input id="audioFile" type="file" accept="audio/*,video/*">
      <audio id="audio" controls preload="metadata"></audio>
      <div class="now">
        <div class="metric"><small>現在時刻</small><strong id="currentTime">00:00:00.000</strong></div>
        <div class="metric"><small>Speaker</small><strong id="currentSpeaker">-</strong></div>
        <div class="metric"><small>IPA token</small><strong id="currentIpa" class="current-word">-</strong></div>
        <div class="metric"><small>Source token</small><strong id="currentText">-</strong></div>
      </div>
    </section>

    <section class="layout">
      <section class="panel">
        <h2>IPA words</h2>
        <div id="words" class="words"></div>
      </section>
      <section class="panel">
        <h2>Turns</h2>
        <div id="turns" class="turns"></div>
      </section>
    </section>
  </main>
  <script id="reviewData" type="application/json">{data_json}</script>
  <script>
    const data = JSON.parse(document.getElementById('reviewData').textContent);
    const audio = document.getElementById('audio');
    const wordsEl = document.getElementById('words');
    const turnsEl = document.getElementById('turns');
    const sourceName = document.getElementById('sourceName');
    const currentTimeEl = document.getElementById('currentTime');
    const currentSpeakerEl = document.getElementById('currentSpeaker');
    const currentIpaEl = document.getElementById('currentIpa');
    const currentTextEl = document.getElementById('currentText');
    const speakerClass = (speaker) => {{
      const match = String(speaker || '').match(/(\\d+)$/);
      const index = match ? Number(match[1]) % 4 : 0;
      return `speaker-${{index}}`;
    }};
    const fmt = (sec) => {{
      const ms = Math.max(0, Math.round(Number(sec || 0) * 1000));
      const h = String(Math.floor(ms / 3600000)).padStart(2, '0');
      const m = String(Math.floor((ms % 3600000) / 60000)).padStart(2, '0');
      const s = String(Math.floor((ms % 60000) / 1000)).padStart(2, '0');
      const x = String(ms % 1000).padStart(3, '0');
      return `${{h}}:${{m}}:${{s}}.${{x}}`;
    }};
    sourceName.textContent = data.source_file || 'audio';
    document.getElementById('audioFile').addEventListener('change', (event) => {{
      const file = event.target.files && event.target.files[0];
      if (!file) return;
      audio.src = URL.createObjectURL(file);
      audio.load();
    }});
    const wordNodes = [];
    const turnNodes = [];
    for (const word of data.words || []) {{
      const button = document.createElement('button');
      button.type = 'button';
      button.className = `word ${{speakerClass(word.speaker)}}`;
      button.dataset.start = word.start;
      button.dataset.end = word.end;
      const ipaLabel = word.ipa || '-';
      button.title = word.text ? `source: ${{word.text}}` : '';
      button.setAttribute('aria-label', word.text ? `${{ipaLabel}} source ${{word.text}}` : ipaLabel);
      button.innerHTML = `<span class="ipa-token">${{ipaLabel}}</span>`;
      button.addEventListener('click', () => {{
        audio.currentTime = Number(word.start || 0);
        audio.play().catch(() => undefined);
      }});
      wordsEl.appendChild(button);
      wordNodes.push([word, button]);
    }}
    for (const turn of data.turns || []) {{
      const row = document.createElement('button');
      row.type = 'button';
      row.className = 'turn';
      row.dataset.start = turn.start;
      row.dataset.end = turn.end;
      row.innerHTML = `<div class="time">${{fmt(turn.start)}} - ${{fmt(turn.end)}}</div><div class="speaker ${{speakerClass(turn.speaker)}}">${{turn.speaker || ''}}</div><div>${{turn.ipa || ''}}</div>`;
      row.addEventListener('click', () => {{
        audio.currentTime = Number(turn.start || 0);
        audio.play().catch(() => undefined);
      }});
      turnsEl.appendChild(row);
      turnNodes.push([turn, row]);
    }}
    let activeWord = null;
    let activeTurn = null;
    const update = () => {{
      const t = audio.currentTime || 0;
      currentTimeEl.textContent = fmt(t);
      const currentWord = wordNodes.find(([word]) => Number(word.start) <= t && t <= Number(word.end));
      const currentTurn = turnNodes.find(([turn]) => Number(turn.start) <= t && t <= Number(turn.end));
      if (activeWord && (!currentWord || activeWord !== currentWord[1])) activeWord.classList.remove('active');
      if (activeTurn && (!currentTurn || activeTurn !== currentTurn[1])) activeTurn.classList.remove('active');
      if (currentWord) {{
        activeWord = currentWord[1];
        activeWord.classList.add('active');
        currentSpeakerEl.textContent = currentWord[0].speaker || '-';
        currentSpeakerEl.className = speakerClass(currentWord[0].speaker);
        currentIpaEl.textContent = currentWord[0].ipa || '-';
        currentTextEl.textContent = currentWord[0].text || '-';
        activeWord.scrollIntoView({{ block: 'nearest', inline: 'nearest' }});
      }}
      if (currentTurn) {{
        activeTurn = currentTurn[1];
        activeTurn.classList.add('active');
        activeTurn.scrollIntoView({{ block: 'nearest' }});
      }}
      requestAnimationFrame(update);
    }};
    update();
  </script>
</body>
</html>
"""
    write_text(output_path, rendered)
    return rendered


def write_review_artifact(
    *,
    media_dir: Path,
    source_info: dict[str, Any],
    transcript_payload: dict[str, Any],
    ipa_turns: list[dict[str, Any]],
    preferred_backend: str | None = None,
    speaker_count: int | None = None,
) -> dict[str, Any]:
    review_dir = media_dir / "review"
    data = build_review_data(
        source_info=source_info,
        transcript_payload=transcript_payload,
        ipa_turns=ipa_turns,
        preferred_backend=preferred_backend,
        speaker_count=speaker_count,
    )
    write_json_atomic(review_dir / "review_data.json", data)
    render_review_html(output_path=review_dir / "review.html", review_data=data)
    return data


def _relative_href(from_path: Path, to_relative_path: str) -> str:
    del from_path
    target = f"../{to_relative_path}"
    return quote(target, safe="/#:-._")


def _file_size_label(path: Path) -> str:
    if not path.exists():
        return "not generated"
    size = path.stat().st_size
    units = ("B", "KB", "MB", "GB")
    value = float(size)
    unit = units[0]
    for unit in units:
        if value < 1024 or unit == units[-1]:
            break
        value /= 1024
    if unit == "B":
        return f"{int(value)} {unit}"
    return f"{value:.1f} {unit}"


def _count_items(value: Any, key: str | None = None) -> int:
    if key and isinstance(value, dict):
        value = value.get(key)
    if isinstance(value, list):
        return len(value)
    return 0


def _existing_file_rows(media_dir: Path, process_html_path: Path, paths: list[tuple[str, str]]) -> str:
    rows: list[str] = []
    for label, relative_path in paths:
        path = media_dir / relative_path
        if path.exists():
            link = f'<a href="{_relative_href(process_html_path, relative_path)}">{escape(relative_path)}</a>'
        else:
            link = f'<span class="missing">{escape(relative_path)}</span>'
        rows.append(
            f"<li><span>{escape(label)}</span><strong>{link}</strong><small>{escape(_file_size_label(path))}</small></li>"
        )
    return "\n".join(rows)


def build_process_review_data(
    *,
    source_info: dict[str, Any],
    cleanup_source_payload: dict[str, Any],
    turns_source_payload: dict[str, Any],
    timeline_payload: dict[str, Any],
    ipa_turns: list[dict[str, Any]],
    readable_text_enabled: bool,
    readable_text_turn_count: int = 0,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "source_file": _source_file_name(source_info),
        "duration_seconds": round(float(source_info.get("duration_seconds") or 0.0), 3),
        "language_hint": str(source_info.get("language_hint") or "und").strip() or "und",
        "source_hash": source_info.get("source_hash"),
        "generation_signature": source_info.get("generation_signature"),
        "pipeline_version": source_info.get("pipeline_version"),
        "compute_mode": source_info.get("compute_mode"),
        "vad_profile": source_info.get("vad_profile"),
        "ipa_backend": source_info.get("effective_ipa_backend") or source_info.get("requested_ipa_backend"),
        "diarization_enabled": bool(source_info.get("diarization_enabled")),
        "diarization_model_id": source_info.get("diarization_model_id"),
        "speech_candidate_count": int(timeline_payload.get("speech_candidate_count") or 0),
        "silence_or_noise_candidate_count": int(timeline_payload.get("silence_or_noise_candidate_count") or 0),
        "timeline_event_count": _count_items(timeline_payload, "events"),
        "cleanup_segment_count": _count_items(cleanup_source_payload, "segments"),
        "turn_segment_count": _count_items(turns_source_payload, "segments"),
        "word_count": _count_items(turns_source_payload, "words"),
        "speaker_turn_count": _count_items(
            turns_source_payload.get("speaker_turns")
            or turns_source_payload.get("diarization_turns")
            or []
        ),
        "ipa_turn_count": len(ipa_turns),
        "readable_text_enabled": readable_text_enabled,
        "readable_text_turn_count": readable_text_turn_count,
        "diarization_used": bool(turns_source_payload.get("diarization_used")),
        "diarization_error": turns_source_payload.get("diarization_error"),
    }


def render_process_review_html(
    *,
    output_path: Path,
    media_dir: Path,
    process_data: dict[str, Any],
    readable_text_enabled: bool,
) -> str:
    data_json = json.dumps(process_data, ensure_ascii=False)
    source_file = str(process_data.get("source_file") or "audio")
    readable_rows = (
        [
            ("Readable Text markdown", "readable-text/Readable Text.md"),
            ("Readable Text turns", "readable-text/readable_text_turns.json"),
            ("Reconstruction metadata", "readable-text/reconstruction.json"),
        ]
        if readable_text_enabled
        else []
    )
    rendered = f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Processing Review - {escape(source_file)}</title>
  <style>
    :root {{
      color-scheme: light dark;
      --bg: #0f172a;
      --panel: #111827;
      --panel-soft: #1f2937;
      --text: #e5e7eb;
      --muted: #94a3b8;
      --line: #334155;
      --accent: #38bdf8;
      --ok: #34d399;
      --warn: #fbbf24;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--text);
      background: radial-gradient(circle at top left, #1e3a8a 0, transparent 34rem), var(--bg);
    }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 24px; }}
    header {{ margin-bottom: 18px; }}
    h1 {{ margin: 0 0 8px; font-size: clamp(28px, 4vw, 48px); letter-spacing: -0.04em; }}
    h2 {{ margin: 0 0 12px; }}
    h3 {{ margin: 0 0 8px; }}
    a {{ color: var(--accent); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    code {{ color: #e0f2fe; }}
    .muted {{ color: var(--muted); }}
    .panel {{
      border: 1px solid var(--line);
      background: color-mix(in srgb, var(--panel) 88%, transparent);
      border-radius: 22px;
      padding: 18px;
      box-shadow: 0 20px 60px rgba(0,0,0,.28);
      margin-bottom: 18px;
    }}
    .metrics {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }}
    .metric {{ background: var(--panel-soft); border-radius: 16px; padding: 14px; min-height: 90px; }}
    .metric small {{ display: block; color: var(--muted); margin-bottom: 6px; }}
    .metric strong {{ font-size: 22px; overflow-wrap: anywhere; }}
    .flow {{ display: grid; gap: 12px; }}
    .step {{ border: 1px solid var(--line); border-radius: 18px; padding: 14px; background: rgba(15,23,42,.45); }}
    .step .tag {{ display: inline-flex; align-items: center; border-radius: 999px; padding: 4px 9px; background: rgba(56,189,248,.14); color: #bae6fd; font-size: 12px; font-weight: 800; margin-bottom: 8px; }}
    .files {{ list-style: none; padding: 0; margin: 12px 0 0; display: grid; gap: 8px; }}
    .files li {{ display: grid; grid-template-columns: minmax(160px, .7fr) minmax(0, 1.4fr) minmax(80px, .25fr); gap: 12px; align-items: baseline; border-top: 1px solid rgba(148,163,184,.18); padding-top: 8px; }}
    .files span {{ color: var(--muted); }}
    .files small {{ color: var(--muted); text-align: right; }}
    .missing {{ color: var(--warn); }}
    .note {{ border-left: 3px solid var(--accent); padding-left: 12px; color: var(--muted); }}
    @media (max-width: 900px) {{
      main {{ padding: 14px; }}
      .metrics, .files li {{ grid-template-columns: 1fr; }}
      .files small {{ text-align: left; }}
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <h1>Processing Review</h1>
      <div class="muted">Source: <code>{escape(source_file)}</code></div>
    </header>

    <section class="panel">
      <h2>Summary</h2>
      <div class="metrics">
        <div class="metric"><small>Audio duration</small><strong id="duration">-</strong></div>
        <div class="metric"><small>Speech candidates</small><strong>{escape(str(process_data.get("speech_candidate_count", 0)))}</strong></div>
        <div class="metric"><small>IPA turns</small><strong>{escape(str(process_data.get("ipa_turn_count", 0)))}</strong></div>
        <div class="metric"><small>Diarization</small><strong>{escape("used" if process_data.get("diarization_used") else "not used")}</strong></div>
      </div>
    </section>

    <section class="panel">
      <h2>How this IPA was made</h2>
      <p class="note">元音声の時間軸は保持したまま、処理用には発話候補だけを短く切り出します。話者は full timeline audio と transcript を照合し、IPA は speaker 付き transcript から作ります。</p>
      <div class="flow">
        <article class="step">
          <div class="tag">1. Source</div>
          <h3>入力ファイルと識別情報</h3>
          <p class="muted">元ファイル名、hash、音声形式、generation signature を記録します。</p>
          <ul class="files">
            {_existing_file_rows(media_dir, output_path, [("Source record", "source.json")])}
          </ul>
        </article>
        <article class="step">
          <div class="tag">2. Audio preparation</div>
          <h3>元の時間軸を持つ音声と、処理用の短い音声</h3>
          <p class="muted">`source-normalized.wav` は元の時間軸を保持します。`normalized.wav` は発話候補だけを詰めた処理用音声です。対応関係は `cut_map.json` に残します。</p>
          <ul class="files">
            {_existing_file_rows(media_dir, output_path, [
                ("Full timeline audio", "audio/source-normalized.wav"),
                ("Speech-candidate audio", "audio/normalized.wav"),
                ("Cut map", "audio/cut_map.json"),
            ])}
          </ul>
        </article>
        <article class="step">
          <div class="tag">3. Timeline scan</div>
          <h3>発話候補・無音候補の記録</h3>
          <p class="muted">発話候補 {escape(str(process_data.get("speech_candidate_count", 0)))} 件、無音またはノイズ候補 {escape(str(process_data.get("silence_or_noise_candidate_count", 0)))} 件を記録します。</p>
          <ul class="files">
            {_existing_file_rows(media_dir, output_path, [
                ("Timeline events markdown", "analysis/Timeline Events.md"),
                ("Timeline events JSON", "analysis/timeline_events.json"),
            ])}
          </ul>
        </article>
        <article class="step">
          <div class="tag">4. Transcript sources</div>
          <h3>IPA化前の発話単位</h3>
          <p class="muted">cleanup source で補助情報を整え、turns source で時刻・単語・話者を持つ発話単位を作ります。</p>
          <ul class="files">
            {_existing_file_rows(media_dir, output_path, [
                ("Cleanup source markdown", "transcript/cleanup-source.md"),
                ("Cleanup source JSON", "transcript/cleanup-source.json"),
                ("Merged context", "transcript/context_merged.txt"),
                ("Turn source markdown", "transcript/turns-source.md"),
                ("Turn source JSON", "transcript/turns-source.json"),
                ("Turn words", "transcript/turns-source_words.json"),
                ("Speaker spans", "transcript/turns-source_speaker_spans.json"),
                ("Transcript delta", "transcript/transcript_delta.json"),
            ])}
          </ul>
        </article>
        <article class="step">
          <div class="tag">5. Speaker alignment</div>
          <h3>話者ラベルの作成</h3>
          <p class="muted">`source-normalized.wav` と turns source を使い、`SPEAKER_00` などの機械的な話者ラベルを発話に合わせます。実名は推測しません。</p>
          <ul class="files">
            {_existing_file_rows(media_dir, output_path, [
                ("Diarization turns", "analysis/diarization_turns.json"),
                ("Speaker summary markdown", "analysis/speaker_summary.md"),
                ("Speaker summary JSON", "analysis/speaker_summary.json"),
                ("Audio features markdown", "analysis/audio_features.md"),
                ("Audio features JSON", "analysis/audio_features.json"),
            ])}
          </ul>
        </article>
        <article class="step">
          <div class="tag">6. IPA artifacts</div>
          <h3>最終IPA</h3>
          <p class="muted">speaker 付き transcript からIPAを作ります。ユーザー向けの主成果物は `IPA.md` です。</p>
          <ul class="files">
            {_existing_file_rows(media_dir, output_path, [
                ("IPA markdown", "ipa/IPA.md"),
                ("IPA turns JSON", "ipa/ipa_turns.json"),
                ("IPA/audio review", "review/review.html"),
                ("IPA/audio review data", "review/review_data.json"),
            ] + readable_rows)}
          </ul>
        </article>
      </div>
    </section>
  </main>
  <script id="processData" type="application/json">{data_json}</script>
  <script>
    const data = JSON.parse(document.getElementById('processData').textContent);
    const fmt = (sec) => {{
      const total = Math.max(0, Math.round(Number(sec || 0)));
      const h = Math.floor(total / 3600);
      const m = Math.floor((total % 3600) / 60);
      const s = total % 60;
      return h ? `${{h}}h ${{m}}m ${{s}}s` : `${{m}}m ${{s}}s`;
    }};
    document.getElementById('duration').textContent = fmt(data.duration_seconds);
  </script>
</body>
</html>
"""
    write_text(output_path, rendered)
    return rendered


def write_process_review_artifact(
    *,
    media_dir: Path,
    source_info: dict[str, Any],
    cleanup_source_payload: dict[str, Any],
    turns_source_payload: dict[str, Any],
    timeline_payload: dict[str, Any],
    ipa_turns: list[dict[str, Any]],
    readable_text_enabled: bool,
    readable_text_turn_count: int = 0,
) -> dict[str, Any]:
    review_dir = media_dir / "review"
    data = build_process_review_data(
        source_info=source_info,
        cleanup_source_payload=cleanup_source_payload,
        turns_source_payload=turns_source_payload,
        timeline_payload=timeline_payload,
        ipa_turns=ipa_turns,
        readable_text_enabled=readable_text_enabled,
        readable_text_turn_count=readable_text_turn_count,
    )
    write_json_atomic(review_dir / "process_data.json", data)
    render_process_review_html(
        output_path=review_dir / "process.html",
        media_dir=media_dir,
        process_data=data,
        readable_text_enabled=readable_text_enabled,
    )
    return data
