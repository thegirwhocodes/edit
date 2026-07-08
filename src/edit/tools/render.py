"""Higher-level social-video render tools.

These tools are the opinionated layer above the primitive FFmpeg wrappers.
They encode Naomi's actual product intent: a user should be able to drop a
clip and say "make this good" without hand-specifying filters or output names.
"""

from __future__ import annotations

import asyncio
import json
import math
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from claude_agent_sdk import tool

from ._safe import ToolError, ok, safe_path


@lru_cache(maxsize=1)
def _has_drawtext() -> bool:
    """Not every ffmpeg build ships the drawtext filter (it needs libfreetype).

    The optional one-line title is a nice-to-have; if this ffmpeg can't draw
    text we skip it gracefully rather than failing the whole render. Real
    word-by-word captions live in tools/captions.py (overlay-based, no
    text-filter dependency).
    """
    if not shutil.which("ffmpeg"):
        return False
    try:
        out = subprocess.run(
            ["ffmpeg", "-hide_banner", "-filters"],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        return False
    return " drawtext " in out.stdout


@dataclass(frozen=True)
class ModeSpec:
    label: str
    description: str
    filters: tuple[str, ...]
    crf: int


MODE_SPECS: dict[str, ModeSpec] = {
    "talking_head": ModeSpec(
        label="Talking Head",
        description="Submagic-style viral teaching clips: crisp, contrasty, caption-forward.",
        filters=(
            "eq=contrast=1.08:saturation=1.10:brightness=0.01",
            "colorbalance=rs=0.025:gs=0.005:bs=-0.025",
            "unsharp=5:5:0.55:3:3:0.20",
        ),
        crf=20,
    ),
    "worship": ModeSpec(
        label="Worship",
        description="Warm, gentle, music-first: golden tone, soft grain, captions should breathe.",
        filters=(
            "eq=contrast=1.03:saturation=1.06:brightness=0.012",
            "colorbalance=rs=0.040:gs=0.008:bs=-0.040",
            "noise=alls=4:allf=t+u",
            "vignette=angle=PI/5",
        ),
        crf=21,
    ),
    "lifestyle": ModeSpec(
        label="Lifestyle",
        description="Warm relatable college-life/vlog polish with natural skin and a clean pop.",
        filters=(
            "eq=contrast=1.06:saturation=1.12:brightness=0.018",
            "colorbalance=rs=0.035:gs=0.010:bs=-0.030",
            "unsharp=5:5:0.35:3:3:0.15",
        ),
        crf=20,
    ),
    "hair_vlog": ModeSpec(
        label="Hair Vlog",
        description="Warm beauty/vlog look: clean skin, richer warmth, subtle sharpness.",
        filters=(
            "eq=contrast=1.07:saturation=1.14:brightness=0.020",
            "colorbalance=rs=0.045:gs=0.012:bs=-0.035",
            "unsharp=5:5:0.40:3:3:0.15",
        ),
        crf=20,
    ),
}


VARIATION_TUNING: dict[str, dict[str, Any]] = {
    "safe": {
        "label": "Safe",
        "filters": (),
        "crf_delta": 0,
        "note": "closest to the selected mode, clean and reliable",
    },
    "stretch": {
        "label": "Stretch",
        "filters": (
            "scale=1120:1992:flags=lanczos",
            "crop=1080:1920",
            "eq=contrast=1.04:saturation=1.04",
        ),
        "crf_delta": 0,
        "note": "slightly tighter crop and richer color for more visual pull",
    },
    "wild": {
        "label": "Wild",
        "filters": (
            "scale=1160:2062:flags=lanczos",
            "crop=1080:1920",
            "eq=contrast=1.10:saturation=1.10",
            "unsharp=7:7:0.65:3:3:0.25",
        ),
        "crf_delta": -1,
        "note": "punchier, closer, more social-first",
    },
}


def _content(payload: dict[str, Any]) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(payload)}]}


async def _run(cmd: list[str], *, timeout: float = 900) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise ToolError(
            "timeout",
            f"Render exceeded {timeout}s: {shlex.join(cmd)}",
            "Try a shorter clip, Safe variation only, or a faster preset.",
        )
    return proc.returncode, stdout.decode(errors="replace"), stderr.decode(errors="replace")


def _base_vertical_filters(width: int = 1080, height: int = 1920) -> list[str]:
    return [
        f"scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos",
        f"crop={width}:{height}",
        "setsar=1",
    ]


def _mode_spec(mode: str) -> ModeSpec:
    mode_key = (mode or "lifestyle").lower().strip()
    if mode_key not in MODE_SPECS:
        valid = ", ".join(sorted(MODE_SPECS))
        raise ToolError(
            "invalid_mode",
            f"mode must be one of {valid}; got {mode!r}.",
            "Use talking_head, worship, lifestyle, or hair_vlog.",
        )
    return MODE_SPECS[mode_key]


def _trim_args(start_sec: Any, end_sec: Any) -> list[str]:
    args: list[str] = []
    if start_sec is not None:
        start = float(start_sec)
        if start < 0:
            raise ToolError("invalid_range", "start_sec must be >= 0.", "Use 0 or omit it.")
        args.extend(["-ss", f"{start:.3f}"])
    if end_sec is not None:
        end = float(end_sec)
        if start_sec is not None and end <= float(start_sec):
            raise ToolError("invalid_range", "end_sec must be greater than start_sec.", "Pick a wider range.")
        if start_sec is not None:
            args.extend(["-t", f"{end - float(start_sec):.3f}"])
        else:
            args.extend(["-to", f"{end:.3f}"])
    return args


def _drawtext_filter(text: str) -> str:
    """Return a conservative bottom title filter for optional simple text."""
    escaped = (
        text.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
        .replace("%", "\\%")
    )
    # Arial Bold exists on stock macOS and keeps FFmpeg drawtext predictable.
    font = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
    return (
        "drawtext="
        f"fontfile='{font}':"
        f"text='{escaped}':"
        "fontcolor=white:"
        "fontsize=54:"
        "borderw=4:"
        "bordercolor=black@0.80:"
        "shadowcolor=black@0.55:"
        "shadowx=2:"
        "shadowy=2:"
        "x=(w-text_w)/2:"
        "y=h*0.73:"
        "box=1:"
        "boxcolor=black@0.38:"
        "boxborderw=20:"
        "enable='between(t,0,6)'"
    )


def _filtergraph(mode: str, variation: str = "safe", title_text: str | None = None) -> str:
    spec = _mode_spec(mode)
    variation_key = (variation or "safe").lower().strip()
    if variation_key not in VARIATION_TUNING:
        valid = ", ".join(sorted(VARIATION_TUNING))
        raise ToolError(
            "invalid_variation",
            f"variation must be one of {valid}; got {variation!r}.",
            "Use safe, stretch, or wild.",
        )

    filters = _base_vertical_filters()
    filters.extend(spec.filters)
    filters.extend(VARIATION_TUNING[variation_key]["filters"])
    # Only add the optional one-line title if this ffmpeg actually has drawtext.
    if title_text and _has_drawtext():
        filters.append(_drawtext_filter(title_text[:80]))
    return ",".join(filters)


async def _render_one(
    *,
    src: Path,
    dst: Path,
    mode: str,
    variation: str,
    start_sec: Any = None,
    end_sec: Any = None,
    title_text: str | None = None,
) -> dict[str, Any]:
    spec = _mode_spec(mode)
    tuning = VARIATION_TUNING[variation]
    dst.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        *_trim_args(start_sec, end_sec),
        "-i", str(src),
        "-map", "0:v:0",
        "-map", "0:a?",
        "-vf", _filtergraph(mode, variation, title_text),
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", str(max(16, spec.crf + int(tuning["crf_delta"]))),
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        str(dst),
    ]
    rc, _, err = await _run(cmd)
    if rc != 0:
        raise ToolError(
            "ffmpeg_failed",
            f"ffmpeg exited {rc}: {err.strip()[:400]}",
            "Try Safe variation, omit title_text, or shorten the clip.",
        )
    if not dst.exists() or dst.stat().st_size == 0:
        raise ToolError(
            "output_missing",
            f"Output file {dst} was not written or is empty.",
            "Retry with a simpler mode or check disk space.",
        )

    return {
        "label": tuning["label"],
        "variation": variation,
        "mode": mode,
        "output_path": str(dst),
        "size_bytes": dst.stat().st_size,
        "note": tuning["note"],
    }


@tool(
    "render_social_clip",
    (
        "Renders a polished 9:16 social-ready clip with Ed.it's built-in "
        "creator looks. Use this when the user says 'upgrade', 'polish', "
        "'make this good', 'make it cinematic', or wants a finished output. "
        "Modes: talking_head (Submagic/viral), worship (warm gentle), "
        "lifestyle, hair_vlog. Returns one downloadable mp4."
    ),
    {
        "source_path": str,
        "output_path": str,
        "mode": str,
        "variation": str,
        "start_sec": float,
        "end_sec": float,
        "title_text": str,
    },
)
async def render_social_clip(args: dict[str, Any]) -> dict[str, Any]:
    try:
        src = safe_path(args["source_path"], must_exist=True, kind="video")
        dst = safe_path(args["output_path"])
        mode = args.get("mode", "lifestyle")
        variation = args.get("variation", "safe")
        title = (args.get("title_text") or "").strip() or None
        rendered = await _render_one(
            src=src,
            dst=dst,
            mode=mode,
            variation=variation,
            start_sec=args.get("start_sec"),
            end_sec=args.get("end_sec"),
            title_text=title,
        )
        return _content(ok({
            **rendered,
            "mode_label": _mode_spec(mode).label,
        }))
    except ToolError as e:
        return _content(e.to_payload())


@tool(
    "render_variations",
    (
        "Renders the full Safe / Stretch / Wild set for an open-ended brief. "
        "Use this instead of asking the user which style they want when the "
        "brief is broad. Outputs three files in output_dir and returns an "
        "`outputs` array with paths and notes."
    ),
    {
        "source_path": str,
        "output_dir": str,
        "mode": str,
        "start_sec": float,
        "end_sec": float,
        "title_text": str,
    },
)
async def render_variations(args: dict[str, Any]) -> dict[str, Any]:
    try:
        src = safe_path(args["source_path"], must_exist=True, kind="video")
        out_dir = safe_path(args.get("output_dir") or "out")
        mode = args.get("mode", "lifestyle")
        title = (args.get("title_text") or "").strip() or None
        out_dir.mkdir(parents=True, exist_ok=True)

        outputs = []
        for idx, variation in enumerate(("safe", "stretch", "wild"), start=1):
            dst = out_dir / f"v{idx}_{variation}.mp4"
            outputs.append(await _render_one(
                src=src,
                dst=dst,
                mode=mode,
                variation=variation,
                start_sec=args.get("start_sec"),
                end_sec=args.get("end_sec"),
                title_text=title,
            ))

        return _content(ok({
            "mode": mode,
            "mode_label": _mode_spec(mode).label,
            "output_count": len(outputs),
            "outputs": outputs,
            "recommendation": "Preview all three; write the user's pick to memory so Ed.it learns the taste.",
        }))
    except ToolError as e:
        return _content(e.to_payload())


@tool(
    "make_contact_sheet",
    (
        "Creates a JPG contact sheet of frames from a video so the user and "
        "agent can quickly inspect visual content without playing the whole "
        "clip. Use after probe_video or before deciding which section to cut."
    ),
    {
        "source_path": str,
        "output_path": str,
        "columns": int,
        "rows": int,
    },
)
async def make_contact_sheet(args: dict[str, Any]) -> dict[str, Any]:
    try:
        src = safe_path(args["source_path"], must_exist=True, kind="video")
        dst = safe_path(args["output_path"])
        columns = max(1, min(6, int(args.get("columns") or 3)))
        rows = max(1, min(6, int(args.get("rows") or 3)))
        frames = columns * rows
        dst.parent.mkdir(parents=True, exist_ok=True)

        # Let ffmpeg sample evenly-ish with thumbnail; enough for quick visual QA.
        thumb_w = max(160, math.floor(1080 / columns))
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(src),
            "-vf", f"select='not(mod(n\\,{max(1, 30 * 2)}))',scale={thumb_w}:-1,tile={columns}x{rows}",
            "-frames:v", "1",
            str(dst),
        ]
        rc, _, err = await _run(cmd, timeout=300)
        if rc != 0:
            raise ToolError(
                "ffmpeg_failed",
                f"ffmpeg exited {rc}: {err.strip()[:300]}",
                "Try fewer rows/columns or a shorter source clip.",
            )
        if not dst.exists() or dst.stat().st_size == 0:
            raise ToolError(
                "output_missing",
                f"Contact sheet {dst} was not written.",
                "Check disk space and retry.",
            )
        return _content(ok({
            "output_path": str(dst),
            "columns": columns,
            "rows": rows,
            "frames_requested": frames,
            "size_bytes": dst.stat().st_size,
        }))
    except ToolError as e:
        return _content(e.to_payload())
