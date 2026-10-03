from __future__ import annotations

import re
from pathlib import Path

from clipsieve.models import TranscriptSegment

_TIME = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{2})\.(\d{3})")
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
# A cue ends at an empty line or where the next timing line starts. A whitespace-only line
# is cue text (YouTube's placeholder line), not a cue break.
_CUE_BREAK = re.compile(r"\n{2,}|\n(?=[^\n]*-->)")


def _to_seconds(stamp: str) -> float:
    m = _TIME.search(stamp)
    if not m:
        raise ValueError(f"bad timestamp: {stamp}")
    h, mi, s, ms = m.groups()
    return int(h or 0) * 3600 + int(mi) * 60 + int(s) + int(ms) / 1000


def _clean(line: str) -> str:
    return _WS.sub(" ", _TAG.sub("", line)).strip()


def parse_vtt(text: str) -> list[TranscriptSegment]:
    """Parse WebVTT, including YouTube's rolling auto-caption cues.

    YouTube repeats the previous line at the top of each cue and emits 10 ms cues
    holding only the completed line. We keep, per cue, only lines not already
    emitted, and drop cues that add nothing.
    """
    segments: list[TranscriptSegment] = []
    seen_lines: list[str] = []
    blocks = _CUE_BREAK.split(text.replace("\r\n", "\n"))
    for block in blocks:
        lines = [ln for ln in block.split("\n") if ln.strip() != ""]
        timing_idx = next((i for i, ln in enumerate(lines) if "-->" in ln), None)
        if timing_idx is None:
            continue
        start_raw, _, rest = lines[timing_idx].partition("-->")
        end_raw = rest.strip().split(" ")[0]
        start_s, end_s = _to_seconds(start_raw), _to_seconds(end_raw)
        fresh: list[str] = []
        for ln in lines[timing_idx + 1 :]:
            cleaned = _clean(ln)
            if not cleaned or cleaned in seen_lines[-2:]:
                continue
            fresh.append(cleaned)
            seen_lines.append(cleaned)
        if not fresh:
            continue
        if end_s <= start_s:
            end_s = start_s + 0.01
        segments.append(TranscriptSegment(start_s=start_s, end_s=end_s, text=" ".join(fresh)))
    return segments


def vtt_lang_from_filename(path: Path) -> str | None:
    parts = path.name.split(".")
    if len(parts) >= 3 and parts[-1] == "vtt":
        return parts[-2]
    return None
