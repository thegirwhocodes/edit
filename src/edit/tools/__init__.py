from .ffmpeg import (
    probe_video,
    trim_clip,
    concat_clips,
    extract_audio,
    transcode,
)
from .gemini import describe_video

ALL_TOOLS = [
    probe_video,
    trim_clip,
    concat_clips,
    extract_audio,
    transcode,
    describe_video,
]