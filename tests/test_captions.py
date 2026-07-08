"""Tests for M7 — transcription + word-by-word captions.

The caption *renderer* is deterministic and tested with synthetic word
timings (no speech model needed). Real transcription is exercised only when
EDIT_RUN_ASR=1 so the default suite stays fast and offline.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from pathlib import Path

import pytest

from edit.tools import add_captions, transcribe_clip
from edit.tools.captions import _group_lines, _style


# A nod to Naomi's first song — "King of all my life, I will sacrifice".
WORDS = [
    {"text": "king", "start": 0.0, "end": 0.3},
    {"text": "of", "start": 0.3, "end": 0.5},
    {"text": "all", "start": 0.5, "end": 0.8},
    {"text": "my", "start": 0.8, "end": 1.0},
    {"text": "life", "start": 1.0, "end": 1.4},
    {"text": "i", "start": 1.4, "end": 1.6},
    {"text": "will", "start": 1.6, "end": 1.8},
    {"text": "sacrifice", "start": 1.8, "end": 2.0},
]


@pytest.fixture(scope="module")
def workdir(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("caption_tests")
    os.environ["EDIT_PROJECT_ROOT"] = str(d)
    return d


@pytest.fixture(scope="module")
def sample_clip(workdir: Path) -> Path:
    """A 2-second vertical-ish clip with video + audio."""
    p = workdir / "talk.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", "testsrc=duration=2:size=360x640:rate=30",
         "-f", "lavfi", "-i", "sine=frequency=300:duration=2",
         "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-shortest", str(p)],
        check=True,
    )
    return p


def _payload(result: dict) -> dict:
    return json.loads(result["content"][0]["text"])


# ---------------------------------------------------------------------------
# grouping logic (pure)
# ---------------------------------------------------------------------------

def test_group_lines_respects_words_per_line():
    lines = _group_lines(WORDS, _style("talking_head"))  # words_per_line=3
    assert len(lines) >= 3
    assert all(len(ln["tokens"]) <= 3 for ln in lines)
    # lines stay time-ordered and cover the words
    assert lines[0]["start"] == 0.0
    assert lines[-1]["end"] == 2.0


def test_group_lines_breaks_on_pause():
    words = [
        {"text": "a", "start": 0.0, "end": 0.2},
        {"text": "b", "start": 1.5, "end": 1.7},  # 1.3s gap -> new line
    ]
    lines = _group_lines(words, _style("worship"))
    assert len(lines) == 2


# ---------------------------------------------------------------------------
# add_captions (deterministic render with synthetic words)
# ---------------------------------------------------------------------------

def test_add_captions_inline_words(sample_clip: Path, workdir: Path):
    dst = workdir / "out" / "talk_captioned.mp4"
    out = asyncio.run(add_captions.handler({
        "source_path": str(sample_clip),
        "output_path": str(dst),
        "mode": "talking_head",
        "words": WORDS,
    }))
    p = _payload(out)
    assert p["status"] == "ok", p
    assert dst.exists() and dst.stat().st_size > 0
    assert p["word_count"] == 8
    assert p["line_count"] >= 3
    assert p["width"] == 360 and p["height"] == 640


def test_add_captions_preserves_dims_and_audio(sample_clip: Path, workdir: Path):
    dst = workdir / "out" / "talk_dims.mp4"
    asyncio.run(add_captions.handler({
        "source_path": str(sample_clip),
        "output_path": str(dst),
        "mode": "worship",
        "words": WORDS,
    }))
    meta = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(dst)],
        capture_output=True, text=True,
    )
    streams = json.loads(meta.stdout)["streams"]
    kinds = {s["codec_type"] for s in streams}
    assert "video" in kinds and "audio" in kinds  # audio survives the overlay
    vid = next(s for s in streams if s["codec_type"] == "video")
    assert vid["width"] == 360 and vid["height"] == 640


def test_add_captions_from_words_path(sample_clip: Path, workdir: Path):
    sidecar = workdir / "talk.words.json"
    sidecar.write_text(json.dumps({"words": WORDS}), encoding="utf-8")
    dst = workdir / "out" / "from_sidecar.mp4"
    out = asyncio.run(add_captions.handler({
        "source_path": str(sample_clip),
        "output_path": str(dst),
        "mode": "talking_head",
        "words_path": str(sidecar),
    }))
    p = _payload(out)
    assert p["status"] == "ok", p
    assert dst.exists() and dst.stat().st_size > 0


def test_add_captions_no_words_errors(sample_clip: Path, workdir: Path):
    out = asyncio.run(add_captions.handler({
        "source_path": str(sample_clip),
        "output_path": str(workdir / "out" / "nope.mp4"),
        "mode": "talking_head",
    }))
    p = _payload(out)
    assert p["status"] == "error"
    assert p["code"] == "no_words"


def test_add_captions_missing_source(workdir: Path):
    out = asyncio.run(add_captions.handler({
        "source_path": str(workdir / "ghost.mp4"),
        "output_path": str(workdir / "out" / "x.mp4"),
        "words": WORDS,
    }))
    p = _payload(out)
    assert p["status"] == "error"
    assert p["code"] == "file_not_found"


# ---------------------------------------------------------------------------
# transcribe_clip — real ASR, opt-in only (downloads a model)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    os.environ.get("EDIT_RUN_ASR") != "1",
    reason="set EDIT_RUN_ASR=1 to run the real transcription test (downloads a model)",
)
def test_transcribe_clip_real(workdir: Path):
    # Generate speech with macOS `say`, mux into a clip, transcribe it.
    aiff = workdir / "speech.aiff"
    subprocess.run(["say", "-o", str(aiff), "king of all my life i will sacrifice"], check=True)
    clip = workdir / "speech.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", "color=c=black:s=360x640:r=30", "-i", str(aiff),
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
         str(clip)],
        check=True,
    )
    out = asyncio.run(transcribe_clip.handler({"source_path": str(clip)}))
    p = _payload(out)
    assert p["status"] == "ok", p
    assert p["word_count"] >= 4
    assert Path(p["words_path"]).exists()
