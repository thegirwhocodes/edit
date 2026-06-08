"""Unit tests for the FFmpeg tool wrappers.

Each tool is exercised against a tiny 2-second test clip we generate with
ffmpeg's testsrc + sine sources — no external fixtures needed.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from pathlib import Path

import pytest

from edit.tools import (
    concat_clips,
    extract_audio,
    probe_video,
    transcode,
    trim_clip,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def workdir(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("edit_tests")
    os.environ["EDIT_PROJECT_ROOT"] = str(d)
    return d


@pytest.fixture(scope="module")
def sample_clip(workdir: Path) -> Path:
    """A 2-second test clip with video + audio."""
    p = workdir / "sample.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=30",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
            "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest",
            str(p),
        ],
        check=True,
    )
    return p


def _payload(result: dict) -> dict:
    """Extract the JSON payload from a tool's content block."""
    return json.loads(result["content"][0]["text"])


# ---------------------------------------------------------------------------
# probe_video
# ---------------------------------------------------------------------------

def test_probe_video_happy(sample_clip: Path):
    out = asyncio.run(probe_video.handler({"path": str(sample_clip)}))
    p = _payload(out)
    assert p["status"] == "ok"
    assert p["width"] == 320
    assert p["height"] == 240
    assert p["video_codec"] == "h264"
    assert p["audio_codec"] == "aac"
    assert 1.9 <= p["duration_sec"] <= 2.1


def test_probe_video_missing_file(workdir: Path):
    out = asyncio.run(probe_video.handler({"path": str(workdir / "nope.mp4")}))
    p = _payload(out)
    assert p["status"] == "error"
    assert p["code"] == "file_not_found"
    assert "hint" in p


def test_probe_video_path_escape(sample_clip: Path):
    out = asyncio.run(probe_video.handler({"path": "/etc/passwd"}))
    p = _payload(out)
    assert p["status"] == "error"
    assert p["code"] == "path_outside_project"


# ---------------------------------------------------------------------------
# trim_clip
# ---------------------------------------------------------------------------

def test_trim_clip_happy(sample_clip: Path, workdir: Path):
    dst = workdir / "trimmed.mp4"
    out = asyncio.run(trim_clip.handler({
        "source_path": str(sample_clip),
        "start_sec": 0.0,
        "end_sec": 1.0,
        "output_path": str(dst),
        "reencode": "always",  # frame-accurate for testing
    }))
    p = _payload(out)
    assert p["status"] == "ok"
    assert dst.exists() and dst.stat().st_size > 0
    assert p["duration_sec"] == 1.0


def test_trim_clip_invalid_range(sample_clip: Path, workdir: Path):
    out = asyncio.run(trim_clip.handler({
        "source_path": str(sample_clip),
        "start_sec": 1.0,
        "end_sec": 0.5,
        "output_path": str(workdir / "bad.mp4"),
    }))
    p = _payload(out)
    assert p["status"] == "error"
    assert p["code"] == "invalid_range"


# ---------------------------------------------------------------------------
# extract_audio
# ---------------------------------------------------------------------------

def test_extract_audio_wav(sample_clip: Path, workdir: Path):
    dst = workdir / "audio.wav"
    out = asyncio.run(extract_audio.handler({
        "source_path": str(sample_clip),
        "output_path": str(dst),
        "format": "wav",
    }))
    p = _payload(out)
    assert p["status"] == "ok"
    assert dst.exists() and dst.stat().st_size > 0


def test_extract_audio_invalid_format(sample_clip: Path, workdir: Path):
    out = asyncio.run(extract_audio.handler({
        "source_path": str(sample_clip),
        "output_path": str(workdir / "x.flac"),
        "format": "flac",
    }))
    p = _payload(out)
    assert p["status"] == "error"
    assert p["code"] == "invalid_format"


# ---------------------------------------------------------------------------
# transcode + concat_clips
# ---------------------------------------------------------------------------

def test_transcode_then_concat(sample_clip: Path, workdir: Path):
    a = workdir / "a.mp4"
    b = workdir / "b.mp4"
    out_a = asyncio.run(transcode.handler({
        "source_path": str(sample_clip),
        "output_path": str(a),
        "codec": "h264",
        "preset": "veryfast",
        "crf": 23,
    }))
    out_b = asyncio.run(transcode.handler({
        "source_path": str(sample_clip),
        "output_path": str(b),
        "codec": "h264",
        "preset": "veryfast",
        "crf": 23,
    }))
    assert _payload(out_a)["status"] == "ok"
    assert _payload(out_b)["status"] == "ok"

    joined = workdir / "joined.mp4"
    out_c = asyncio.run(concat_clips.handler({
        "input_paths": [str(a), str(b)],
        "output_path": str(joined),
    }))
    p = _payload(out_c)
    assert p["status"] == "ok"
    assert joined.exists() and joined.stat().st_size > 0