from .ffmpeg import (
    probe_video,
    trim_clip,
    concat_clips,
    extract_audio,
    transcode,
)
from .gemini import describe_video
from .render import (
    make_contact_sheet,
    render_social_clip,
    render_variations,
)
from .captions import (
    transcribe_clip,
    add_captions,
)
from .memory_tools import (
    memory_recall,
    memory_write,
    preference_set,
    profile_write,
)

ALL_TOOLS = [
    # Video understanding
    describe_video,
    make_contact_sheet,
    render_social_clip,
    render_variations,
    # Captions (M7): transcribe -> word-by-word burn-in
    transcribe_clip,
    add_captions,
    # FFmpeg primitives
    probe_video,
    trim_clip,
    concat_clips,
    extract_audio,
    transcode,
    # Memory / personalization
    memory_recall,
    memory_write,
    preference_set,
    profile_write,
]
