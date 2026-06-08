"""FFmpeg-backed video tools exposed to the agent via the Claude Agent SDK.

Each tool is a curated wrapper around a specific FFmpeg invocation we've
tested. The agent never sees `ffmpeg` directly — it sees verb-named tools
with structured schemas and structured returns.
"""

from __future__ import annotations

import asyncio
import json
import shlex
from pathlib import Path
from typing import Any

from claude_agent_sdk import tool

from ._safe import ToolError, ok, safe_path


# ---------------------------------------------------------------------------
# Subprocess helper
# ---------------------------------------------------------------------------

async def _run(cmd: list[str], *, timeout: float = 600) -> tuple[int, str, str]:
    """Run a subprocess, return (returncode, stdout, stderr). Never shell=True."""
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
            f"Subprocess exceeded {timeout}s: {shlex.join(cmd)}",
            "Try a smaller clip or a faster preset.",
        )
    return proc.returncode, stdout.decode(errors="replace"), stderr.decode(errors="replace")


def _content(payload: dict[str, Any]) -> dict[str, Any]:
    """Format payload as the SDK's expected tool-result content block."""
    return {"content": [{"type": "text", "text": json.dumps(payload)}]}


# ---------------------------------------------------------------------------
# probe_video
# ---------------------------------------------------------------------------

@tool(
    "probe_video",
    (
        "Returns duration, resolution, frame rate, and codec info for a video "
        "file. Use this first to understand a clip before editing — never guess "
        "duration or resolution. Returns a JSON object with `duration_sec`, "
        "`width`, `height`, `fps`, `video_codec`, `audio_codec`."
    ),
    {"path": str},
)
async def probe_video(args: dict[str, Any]) -> dict[str, Any]:
    try:
        path = safe_path(args["path"], must_exist=True, kind="video")
        rc, out, err = await _run([
            "ffprobe", "-v", "error",
            "-print_format", "json",
            "-show_format", "-show_streams",
            str(path),
        ])
        if rc != 0:
            raise ToolError(
                "ffprobe_failed",
                f"ffprobe exited {rc}: {err.strip()[:200]}",
                "Verify the file is a video. Try a re-encoded copy if it's a "
                "broken QuickTime container.",
            )
        meta = json.loads(out)
        video = next((s for s in meta.get("streams", []) if s.get("codec_type") == "video"), None)
        audio = next((s for s in meta.get("streams", []) if s.get("codec_type") == "audio"), None)
        fmt = meta.get("format", {})

        fps = None
        if video and video.get("avg_frame_rate"):
            num, _, den = video["avg_frame_rate"].partition("/")
            try:
                fps = round(float(num) / float(den), 3) if float(den) else None
            except (ValueError, ZeroDivisionError):
                fps = None

        return _content(ok({
            "path": str(path),
            "duration_sec": float(fmt.get("duration", 0)) if fmt.get("duration") else None,
            "size_bytes": int(fmt.get("size", 0)) if fmt.get("size") else None,
            "width": video.get("width") if video else None,
            "height": video.get("height") if video else None,
            "fps": fps,
            "video_codec": video.get("codec_name") if video else None,
            "audio_codec": audio.get("codec_name") if audio else None,
        }))
    except ToolError as e:
        return _content(e.to_payload())


# ---------------------------------------------------------------------------
# trim_clip
# ---------------------------------------------------------------------------

@tool(
    "trim_clip",
    (
        "Cuts a segment from a source video between two timestamps and writes "
        "a new file. Use when the user wants to shorten a clip, extract a "
        "highlight, or isolate a moment. Stream-copies (no re-encode) by "
        "default — fast and lossless. Set `reencode=always` for frame-accurate "
        "cuts. Returns the output path and actual duration."
    ),
    {
        "source_path": str,
        "start_sec": float,
        "end_sec": float,
        "output_path": str,
        "reencode": str,  # "never" | "if_needed" | "always"
    },
)
async def trim_clip(args: dict[str, Any]) -> dict[str, Any]:
    try:
        src = safe_path(args["source_path"], must_exist=True, kind="video")
        dst = safe_path(args["output_path"])
        start = float(args["start_sec"])
        end = float(args["end_sec"])
        reencode = args.get("reencode", "if_needed")

        if end <= start:
            raise ToolError(
                "invalid_range",
                f"end_sec ({end}) must be greater than start_sec ({start}).",
                "Swap the arguments or pick a wider range.",
            )
        if start < 0:
            raise ToolError(
                "invalid_range",
                f"start_sec ({start}) must be >= 0.",
                "Use 0 to start from the beginning.",
            )

        dst.parent.mkdir(parents=True, exist_ok=True)
        duration = end - start

        if reencode == "always":
            codec_args = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                          "-c:a", "aac", "-b:a", "192k"]
        elif reencode == "never":
            codec_args = ["-c", "copy"]
        else:  # if_needed: try stream copy, fall back below
            codec_args = ["-c", "copy"]

        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-ss", f"{start}", "-i", str(src),
            "-t", f"{duration}",
            *codec_args,
            str(dst),
        ]
        rc, _, err = await _run(cmd)

        reencoded = False
        if rc != 0 and reencode == "if_needed":
            # Stream copy can fail on keyframe misalignment — fall back to re-encode
            cmd_fb = [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-ss", f"{start}", "-i", str(src),
                "-t", f"{duration}",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-c:a", "aac", "-b:a", "192k",
                str(dst),
            ]
            rc, _, err = await _run(cmd_fb)
            reencoded = True
        elif reencode == "always":
            reencoded = True

        if rc != 0:
            raise ToolError(
                "ffmpeg_failed",
                f"ffmpeg exited {rc}: {err.strip()[:200]}",
                "Check that the output directory is writable and the source "
                "has a video stream.",
            )

        # Verify output actually exists and is non-zero
        if not dst.exists() or dst.stat().st_size == 0:
            raise ToolError(
                "output_missing",
                f"Output file {dst} was not written or is empty.",
                "Retry with `reencode=always` for frame-accurate cuts.",
            )

        return _content(ok({
            "output_path": str(dst),
            "duration_sec": round(duration, 3),
            "reencoded": reencoded,
            "size_bytes": dst.stat().st_size,
        }))
    except ToolError as e:
        return _content(e.to_payload())


# ---------------------------------------------------------------------------
# concat_clips
# ---------------------------------------------------------------------------

@tool(
    "concat_clips",
    (
        "Joins multiple video clips end-to-end into a single output file. All "
        "inputs should share the same codec, resolution, and frame rate (use "
        "transcode first if they don't). Returns the output path."
    ),
    {
        "input_paths": list,  # list[str]
        "output_path": str,
    },
)
async def concat_clips(args: dict[str, Any]) -> dict[str, Any]:
    try:
        if not args.get("input_paths"):
            raise ToolError(
                "missing_inputs",
                "input_paths is empty.",
                "Pass at least one video path in input_paths.",
            )

        inputs = [safe_path(p, must_exist=True, kind="video") for p in args["input_paths"]]
        dst = safe_path(args["output_path"])
        dst.parent.mkdir(parents=True, exist_ok=True)

        # Use the concat demuxer (fastest, requires matching codecs)
        list_file = dst.with_suffix(".concat.txt")
        list_file.write_text(
            "\n".join(f"file {shlex.quote(str(p))}" for p in inputs),
            encoding="utf-8",
        )
        try:
            cmd = [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-f", "concat", "-safe", "0",
                "-i", str(list_file),
                "-c", "copy",
                str(dst),
            ]
            rc, _, err = await _run(cmd)
            if rc != 0:
                raise ToolError(
                    "concat_failed",
                    f"ffmpeg concat exited {rc}: {err.strip()[:200]}",
                    "Inputs likely differ in codec or resolution. Run "
                    "transcode on each to normalize, then retry.",
                )
        finally:
            list_file.unlink(missing_ok=True)

        return _content(ok({
            "output_path": str(dst),
            "input_count": len(inputs),
            "size_bytes": dst.stat().st_size,
        }))
    except ToolError as e:
        return _content(e.to_payload())


# ---------------------------------------------------------------------------
# extract_audio
# ---------------------------------------------------------------------------

@tool(
    "extract_audio",
    (
        "Pulls the audio track out of a video file as a standalone WAV or M4A. "
        "Useful before sending audio to Whisper for transcription. Returns the "
        "output path."
    ),
    {
        "source_path": str,
        "output_path": str,
        "format": str,  # "wav" | "m4a"
    },
)
async def extract_audio(args: dict[str, Any]) -> dict[str, Any]:
    try:
        src = safe_path(args["source_path"], must_exist=True, kind="video")
        dst = safe_path(args["output_path"])
        fmt = args.get("format", "wav").lower()

        if fmt not in ("wav", "m4a"):
            raise ToolError(
                "invalid_format",
                f"format must be 'wav' or 'm4a', got {fmt!r}.",
                "Pass 'wav' for transcription, 'm4a' for compressed audio.",
            )

        dst.parent.mkdir(parents=True, exist_ok=True)
        if fmt == "wav":
            codec_args = ["-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1"]
        else:
            codec_args = ["-vn", "-acodec", "aac", "-b:a", "192k"]

        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(src), *codec_args, str(dst),
        ]
        rc, _, err = await _run(cmd)
        if rc != 0:
            raise ToolError(
                "ffmpeg_failed",
                f"ffmpeg exited {rc}: {err.strip()[:200]}",
                "Verify the source has an audio stream (run probe_video).",
            )
        return _content(ok({
            "output_path": str(dst),
            "format": fmt,
            "size_bytes": dst.stat().st_size,
        }))
    except ToolError as e:
        return _content(e.to_payload())


# ---------------------------------------------------------------------------
# transcode
# ---------------------------------------------------------------------------

@tool(
    "transcode",
    (
        "Re-encodes a video to a target codec / container. Use to normalize "
        "clips before concat, to compress for upload, or to convert containers. "
        "Common combinations: codec=h264 + container=mp4 for delivery; "
        "codec=h265 + container=mp4 for smaller files; codec=prores + "
        "container=mov for editing intermediate."
    ),
    {
        "source_path": str,
        "output_path": str,
        "codec": str,        # "h264" | "h265" | "prores"
        "preset": str,       # "veryfast" | "fast" | "medium" | "slow"
        "crf": int,          # 18 (high quality) .. 28 (low)
        "width": int,        # optional, omit to keep source width
    },
)
async def transcode(args: dict[str, Any]) -> dict[str, Any]:
    try:
        src = safe_path(args["source_path"], must_exist=True, kind="video")
        dst = safe_path(args["output_path"])
        codec = args.get("codec", "h264").lower()
        preset = args.get("preset", "veryfast")
        crf = int(args.get("crf", 20))
        width = args.get("width")

        codec_map = {
            "h264": ["-c:v", "libx264", "-preset", preset, "-crf", str(crf)],
            "h265": ["-c:v", "libx265", "-preset", preset, "-crf", str(crf)],
            "prores": ["-c:v", "prores_ks", "-profile:v", "3"],  # standard
        }
        if codec not in codec_map:
            raise ToolError(
                "invalid_codec",
                f"codec must be one of {list(codec_map)}, got {codec!r}.",
                "Pick h264 for delivery, h265 for size, prores for editing.",
            )

        filters = []
        if width:
            filters.append(f"scale={width}:-2")  # -2 keeps even height
        vf = ["-vf", ",".join(filters)] if filters else []

        dst.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(src),
            *vf,
            *codec_map[codec],
            "-c:a", "aac", "-b:a", "192k",
            str(dst),
        ]
        rc, _, err = await _run(cmd)
        if rc != 0:
            raise ToolError(
                "ffmpeg_failed",
                f"ffmpeg exited {rc}: {err.strip()[:200]}",
                "Try a faster preset, or lower crf if it's a memory error.",
            )
        return _content(ok({
            "output_path": str(dst),
            "codec": codec,
            "preset": preset,
            "crf": crf,
            "size_bytes": dst.stat().st_size,
        }))
    except ToolError as e:
        return _content(e.to_payload())
