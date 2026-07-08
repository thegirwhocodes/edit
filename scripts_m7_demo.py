"""Throwaway M7 end-to-end proof: speech -> transcribe -> grade -> caption."""
import asyncio, json, os, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "Ed.it Projects"
os.environ["EDIT_PROJECT_ROOT"] = str(ROOT)
(ROOT / "inbox").mkdir(parents=True, exist_ok=True)
(ROOT / "out").mkdir(parents=True, exist_ok=True)

from edit.tools import transcribe_clip, add_captions, render_social_clip

LINE = "King of all my life I will sacrifice everything for you"
aiff = ROOT / "inbox" / "m7_speech.aiff"
src = ROOT / "inbox" / "m7_demo_src.mp4"
graded = ROOT / "out" / "m7_demo_graded.mp4"
final = ROOT / "out" / "m7_demo_captioned.mp4"

subprocess.run(["say", "-r", "150", "-o", str(aiff), LINE], check=True)
subprocess.run([
    "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
    "-f", "lavfi", "-i", "color=c=0x1a2b3c:s=1080x1920:r=30",
    "-i", str(aiff),
    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
    str(src),
], check=True)

def run(coro):
    return json.loads(asyncio.run(coro)["content"][0]["text"])

print("1) transcribe (downloads base.en on first run)…")
t = run(transcribe_clip.handler({"source_path": str(src)}))
print("   ", {k: t.get(k) for k in ("status", "word_count", "language", "text_preview")})

print("2) grade (talking_head)…")
g = run(render_social_clip.handler({
    "source_path": str(src), "output_path": str(graded),
    "mode": "talking_head", "variation": "safe",
}))
print("   ", {k: g.get(k) for k in ("status", "output_path")})

print("3) caption (word-by-word, talking_head)…")
c = run(add_captions.handler({
    "source_path": str(graded), "output_path": str(final),
    "mode": "talking_head", "words_path": t["words_path"],
}))
print("   ", {k: c.get(k) for k in ("status", "output_path", "word_count", "line_count", "size_bytes")})
print("DONE ->", final)
