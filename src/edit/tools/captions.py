"""M7 — transcription + Submagic-style word-by-word captions.

This is the feature Naomi asked for first, back in the DaVinci days: captions
where the active word pops as it's spoken. We build it the way the research
(docs/10) and the March pivot pointed to, adapted to what this machine can
actually do:

* **Transcription** — `faster-whisper` (CTranslate2, no torch) gives
  word-level timestamps locally. `transcribe_clip` writes a sidecar
  `*.words.json` so captions consume an artifact instead of round-tripping a
  big word array through the model.
* **Caption render** — this machine's ffmpeg has *no* text filters (no
  libass, no drawtext/freetype), but it does have `overlay`. So we draw the
  caption track with Pillow (Montserrat, installed), encode it as a
  transparent VP9 video, and overlay it onto the source. Fully deterministic,
  no system-ffmpeg surgery.

The two tools are decoupled on purpose: `add_captions` is a pure function of
(video, word timings, style) and is unit-tested with synthetic words — no ASR
needed in the test path.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from claude_agent_sdk import tool

from ._safe import ToolError, ok, safe_path


def _content(payload: dict[str, Any]) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(payload)}]}


# ---------------------------------------------------------------------------
# Fonts
# ---------------------------------------------------------------------------

_FONT_DIRS = [
    Path.home() / "Library" / "Fonts",
    Path("/Library/Fonts"),
    Path("/System/Library/Fonts/Supplemental"),
]
_FALLBACK_FONT = Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf")


def _font_path(weight: str) -> str:
    """Find a Montserrat weight on disk, falling back to a stock system bold."""
    for d in _FONT_DIRS:
        cand = d / f"Montserrat-{weight}.ttf"
        if cand.exists():
            return str(cand)
    # Any Montserrat at all is better than Arial
    for d in _FONT_DIRS:
        if d.exists():
            for f in sorted(d.glob("Montserrat-*.ttf")):
                return str(f)
    return str(_FALLBACK_FONT)


# ---------------------------------------------------------------------------
# Per-mode caption look. Worship is deliberately gentle (no harsh highlight,
# warm cream, lower in frame) so captions don't overpower the song.
# ---------------------------------------------------------------------------

CAPTION_STYLES: dict[str, dict[str, Any]] = {
    "talking_head": dict(
        weight="Black", caps=True, rel_size=0.060, y_rel=0.60,
        fill="#FFFFFF", active="#FFCE34", stroke_rel=0.012,
        pill=True, pill_rgb=(15, 15, 15), pill_alpha=180,
        words_per_line=3, max_line_sec=2.2,
    ),
    "lifestyle": dict(
        weight="Bold", caps=True, rel_size=0.050, y_rel=0.74,
        fill="#FFFFFF", active="#FFD28A", stroke_rel=0.010,
        pill=True, pill_rgb=(20, 16, 12), pill_alpha=150,
        words_per_line=4, max_line_sec=2.4,
    ),
    "hair_vlog": dict(
        weight="Bold", caps=False, rel_size=0.048, y_rel=0.74,
        fill="#FFFFFF", active="#FFD28A", stroke_rel=0.009,
        pill=True, pill_rgb=(20, 16, 12), pill_alpha=140,
        words_per_line=4, max_line_sec=2.4,
    ),
    "worship": dict(
        weight="SemiBold", caps=False, rel_size=0.040, y_rel=0.80,
        fill="#FFF5E6", active=None, stroke_rel=0.006,
        pill=False, pill_rgb=(0, 0, 0), pill_alpha=0,
        words_per_line=3, max_line_sec=3.0,
    ),
}


def _style(mode: str | None) -> dict[str, Any]:
    return CAPTION_STYLES.get((mode or "talking_head").lower().strip(),
                              CAPTION_STYLES["talking_head"])


def _hex(c: str) -> tuple[int, int, int]:
    c = c.lstrip("#")
    return (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16))


# ---------------------------------------------------------------------------
# Transcription (faster-whisper)
# ---------------------------------------------------------------------------

_MODEL_CACHE: dict[str, Any] = {}


def _get_model(name: str):
    if name not in _MODEL_CACHE:
        from faster_whisper import WhisperModel  # lazy, optional dep
        # int8 on CPU: small + fast, no torch/GPU needed.
        _MODEL_CACHE[name] = WhisperModel(name, device="cpu", compute_type="int8")
    return _MODEL_CACHE[name]


def transcribe_words(
    media_path: Path, *, model_name: str | None = None, language: str | None = None
) -> dict[str, Any]:
    """Return word-level timestamps for a media file. Pure helper (no @tool)."""
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        raise ToolError(
            "missing_dependency",
            "faster-whisper is not installed.",
            "Run: pip install 'edit[captions]'  (or pip install faster-whisper).",
        )

    name = model_name or os.environ.get("EDIT_WHISPER_MODEL", "base.en")
    try:
        model = _get_model(name)
        segments, info = model.transcribe(
            str(media_path),
            word_timestamps=True,
            language=language,
            vad_filter=True,
        )
        words: list[dict[str, Any]] = []
        seg_list: list[dict[str, Any]] = []
        for seg in segments:
            seg_list.append({
                "start": round(float(seg.start), 3),
                "end": round(float(seg.end), 3),
                "text": seg.text.strip(),
            })
            for w in (seg.words or []):
                token = (w.word or "").strip()
                if not token:
                    continue
                words.append({
                    "text": token,
                    "start": round(float(w.start), 3),
                    "end": round(float(w.end), 3),
                })
    except ToolError:
        raise
    except Exception as e:  # model load / decode failures
        raise ToolError(
            "transcribe_failed",
            f"Transcription failed: {type(e).__name__}: {e}",
            "Check the file has an audio track (probe_video), or try a different "
            "EDIT_WHISPER_MODEL.",
        )

    return {
        "words": words,
        "segments": seg_list,
        "language": getattr(info, "language", language),
        "duration": round(float(getattr(info, "duration", 0.0)), 3),
    }


@tool(
    "transcribe_clip",
    (
        "Transcribes a clip's speech into WORD-LEVEL timestamps using a local "
        "Whisper model (no upload of the video; runs on your machine). Writes a "
        "`<name>.words.json` sidecar next to the clip and returns its path plus "
        "a short text preview. Call this before `add_captions`. Needs an audio "
        "track — run `probe_video` first if unsure."
    ),
    {"source_path": str, "model": str, "language": str},
)
async def transcribe_clip(args: dict[str, Any]) -> dict[str, Any]:
    try:
        src = safe_path(args["source_path"], must_exist=True, kind="video")
        model = (args.get("model") or "").strip() or None
        language = (args.get("language") or "").strip() or None

        result = await asyncio.to_thread(
            transcribe_words, src, model_name=model, language=language
        )
        words = result["words"]
        if not words:
            raise ToolError(
                "no_speech",
                "No words were transcribed (the clip may have no audio or no speech).",
                "Run probe_video to confirm an audio track exists.",
            )

        words_path = src.with_suffix(src.suffix + ".words.json")
        words_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        full_text = " ".join(w["text"] for w in words)

        return _content(ok({
            "words_path": str(words_path),
            "word_count": len(words),
            "language": result["language"],
            "duration_sec": result["duration"],
            "text_preview": full_text[:280] + ("…" if len(full_text) > 280 else ""),
        }))
    except ToolError as e:
        return _content(e.to_payload())


# ---------------------------------------------------------------------------
# Caption rendering
# ---------------------------------------------------------------------------

def _probe_dims(path: Path) -> tuple[int, int, float, float]:
    """(width, height, fps, duration_sec) via ffprobe."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,avg_frame_rate:format=duration",
         "-of", "json", str(path)],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        raise ToolError("ffprobe_failed", f"ffprobe failed on {path.name}.",
                        "Confirm the file is a video (probe_video).")
    meta = json.loads(out.stdout)
    stream = (meta.get("streams") or [{}])[0]
    width = int(stream.get("width") or 1080)
    height = int(stream.get("height") or 1920)
    num, _, den = (stream.get("avg_frame_rate") or "30/1").partition("/")
    try:
        fps = float(num) / float(den) if float(den) else 30.0
    except (ValueError, ZeroDivisionError):
        fps = 30.0
    duration = float((meta.get("format") or {}).get("duration") or 0.0)
    return width, height, round(fps, 3) or 30.0, duration


def _group_lines(words: list[dict[str, Any]], style: dict[str, Any]) -> list[dict[str, Any]]:
    """Group words into short caption lines (a few words shown at a time)."""
    per = int(style["words_per_line"])
    max_sec = float(style["max_line_sec"])
    lines: list[dict[str, Any]] = []
    cur: list[dict[str, Any]] = []
    for w in words:
        if cur:
            line_start = cur[0]["start"]
            gap = w["start"] - cur[-1]["end"]
            too_long = (w["end"] - line_start) > max_sec
            if len(cur) >= per or gap > 0.7 or too_long:
                lines.append(cur)
                cur = []
        cur.append(w)
    if cur:
        lines.append(cur)
    return [{"tokens": ln, "start": ln[0]["start"], "end": ln[-1]["end"]} for ln in lines]


def render_caption_overlay(
    source_path: Path,
    words: list[dict[str, Any]],
    output_path: Path,
    *,
    mode: str = "talking_head",
) -> dict[str, Any]:
    """Burn Submagic-style word-by-word captions onto a clip. Pure helper.

    Pipeline: Pillow draws each caption state → raw RGBA piped to ffmpeg →
    transparent VP9 (`yuva420p`) caption track → `overlay` onto the source.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont  # lazy, optional dep
    except ImportError:
        raise ToolError(
            "missing_dependency",
            "Pillow is not installed.",
            "Run: pip install 'edit[captions]'  (or pip install pillow).",
        )

    if not words:
        raise ToolError("no_words", "No words to render.",
                        "Call transcribe_clip first, or pass a non-empty words list.")

    style = _style(mode)
    W, H, fps, duration = _probe_dims(source_path)
    if duration <= 0:
        duration = max(w["end"] for w in words) + 0.3
    total_frames = max(1, round(duration * fps))

    caps = bool(style["caps"])
    tokens_all = [
        {**w, "disp": (w["text"].upper() if caps else w["text"])}
        for w in words
    ]
    lines = _group_lines(tokens_all, style)

    font_size = max(18, int(H * style["rel_size"]))
    stroke_w = max(1, int(H * style["stroke_rel"]))
    font = ImageFont.truetype(_font_path(style["weight"]), font_size)
    space_w = max(1, int(font_size * 0.30))
    fill = _hex(style["fill"])
    active_rgb = _hex(style["active"]) if style["active"] else None
    max_w = int(W * 0.88)

    blank = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    blank_bytes = blank.tobytes()

    # Render one caption state (a given line with a given active word) into a
    # small block image; cache by (line_idx, active_idx).
    state_cache: dict[tuple[int, int], bytes] = {}

    def _render_state(line_idx: int, active_idx: int) -> bytes:
        key = (line_idx, active_idx)
        cached = state_cache.get(key)
        if cached is not None:
            return cached
        toks = lines[line_idx]["tokens"]
        widths = [int(ImageDraw.Draw(blank).textlength(t["disp"], font=font)) for t in toks]
        text_w = sum(widths) + space_w * (len(toks) - 1)
        x0 = max(0, (W - text_w) // 2)
        baseline_y = int(H * style["y_rel"])

        canvas = blank.copy()
        draw = ImageDraw.Draw(canvas)

        if style["pill"]:
            pad_x, pad_y = int(font_size * 0.45), int(font_size * 0.32)
            radius = int(font_size * 0.35)
            top = baseline_y - font_size // 2 - pad_y
            bot = baseline_y + font_size // 2 + pad_y
            draw.rounded_rectangle(
                [x0 - pad_x, top, x0 + text_w + pad_x, bot],
                radius=radius,
                fill=(*style["pill_rgb"], int(style["pill_alpha"])),
            )

        x = x0
        for i, t in enumerate(toks):
            color = active_rgb if (active_rgb and i == active_idx) else fill
            draw.text(
                (x, baseline_y), t["disp"], font=font, fill=(*color, 255),
                stroke_width=stroke_w, stroke_fill=(0, 0, 0, 255), anchor="lm",
            )
            x += widths[i] + space_w

        data = canvas.tobytes()
        state_cache[key] = data
        return data

    def _state_for_time(t: float) -> tuple[int, int] | None:
        for li, ln in enumerate(lines):
            # show the line slightly early/late so it doesn't flicker on cuts
            if ln["start"] - 0.05 <= t <= ln["end"] + 0.20:
                toks = ln["tokens"]
                ai = 0
                for i, tok in enumerate(toks):
                    if t >= tok["start"] - 0.02:
                        ai = i
                return (li, ai)
        return None

    # --- Pass 1: Pillow -> raw RGBA -> transparent VP9 caption track ---
    caption_track = output_path.with_suffix(".captions.webm")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    enc = subprocess.Popen(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "rawvideo", "-pixel_format", "rgba",
         "-video_size", f"{W}x{H}", "-framerate", f"{fps}",
         "-i", "-", "-an",
         "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p",
         "-b:v", "0", "-crf", "30", "-auto-alt-ref", "0",
         str(caption_track)],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    assert enc.stdin is not None
    last_state: object = object()
    last_bytes = blank_bytes
    try:
        for f in range(total_frames):
            t = (f + 0.5) / fps
            st = _state_for_time(t)
            if st != last_state:
                last_bytes = blank_bytes if st is None else _render_state(*st)
                last_state = st
            enc.stdin.write(last_bytes)
        enc.stdin.close()
    except BrokenPipeError:
        pass
    err = enc.stderr.read().decode(errors="replace") if enc.stderr else ""
    if enc.wait() != 0:
        raise ToolError("caption_encode_failed",
                        f"VP9 caption-track encode failed: {err.strip()[:300]}",
                        "Confirm this ffmpeg has libvpx (vp9 + alpha).")

    # --- Pass 2: overlay caption track onto the source, keep audio ---
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(source_path), "-i", str(caption_track),
        "-filter_complex", "[0:v][1:v]overlay=0:0:format=auto:eof_action=pass[v]",
        "-map", "[v]", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart", str(output_path),
    ]
    out = subprocess.run(cmd, capture_output=True, text=True)
    caption_track.unlink(missing_ok=True)
    if out.returncode != 0:
        raise ToolError("overlay_failed",
                        f"Caption overlay failed: {out.stderr.strip()[:300]}",
                        "Retry, or check disk space.")
    if not output_path.exists() or output_path.stat().st_size == 0:
        raise ToolError("output_missing", f"{output_path} was not written.",
                        "Check disk space and retry.")

    return {
        "output_path": str(output_path),
        "mode": mode,
        "word_count": len(words),
        "line_count": len(lines),
        "size_bytes": output_path.stat().st_size,
        "width": W, "height": H,
    }


def _load_words(words_arg: Any, words_path: str | None) -> list[dict[str, Any]]:
    """Accept inline words or a path to a transcribe_clip sidecar JSON."""
    if isinstance(words_arg, list) and words_arg:
        return [
            {"text": str(w.get("text") or w.get("word") or "").strip(),
             "start": float(w["start"]), "end": float(w["end"])}
            for w in words_arg
            if (w.get("text") or w.get("word")) and "start" in w and "end" in w
        ]
    if words_path:
        p = safe_path(words_path, must_exist=True, kind="words file")
        data = json.loads(p.read_text(encoding="utf-8"))
        raw = data.get("words", data) if isinstance(data, dict) else data
        return [
            {"text": str(w.get("text") or w.get("word") or "").strip(),
             "start": float(w["start"]), "end": float(w["end"])}
            for w in raw
            if (w.get("text") or w.get("word")) and "start" in w and "end" in w
        ]
    return []


@tool(
    "add_captions",
    (
        "Burns Submagic-style word-by-word captions onto a clip — the active "
        "word pops as it's spoken (yellow highlight for talking_head/lifestyle; "
        "gentle warm captions for worship that don't overpower the music). "
        "Provide `words_path` from a prior `transcribe_clip` call (preferred), "
        "or pass an inline `words` array of {text,start,end}. Modes: "
        "talking_head, lifestyle, hair_vlog, worship. Returns the captioned mp4. "
        "Tip: caption AFTER render_social_clip so captions sit on the graded clip."
    ),
    {
        "source_path": str,
        "output_path": str,
        "mode": str,
        "words_path": str,
        "words": list,
    },
)
async def add_captions(args: dict[str, Any]) -> dict[str, Any]:
    try:
        src = safe_path(args["source_path"], must_exist=True, kind="video")
        dst = safe_path(args["output_path"])
        mode = (args.get("mode") or "talking_head").strip()
        words = _load_words(args.get("words"), args.get("words_path"))
        if not words:
            raise ToolError(
                "no_words",
                "No word timings provided.",
                "Call transcribe_clip first and pass its words_path, or pass an "
                "inline words array of {text,start,end}.",
            )
        result = await asyncio.to_thread(
            render_caption_overlay, src, words, dst, mode=mode
        )
        return _content(ok(result))
    except ToolError as e:
        return _content(e.to_payload())
