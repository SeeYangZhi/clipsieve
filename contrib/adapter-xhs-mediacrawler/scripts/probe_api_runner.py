# contrib/adapter-xhs-mediacrawler/scripts/probe_api_runner.py
"""One video-only search page through the api runner against the user's browser session.

Run from contrib/adapter-xhs-mediacrawler:
    uv run python scripts/probe_api_runner.py "新加坡搬到上海" [pages]
Prints counts and timing only; writes nothing. Not a test; needs Brave on the CDP port, logged in.
"""

from __future__ import annotations

import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from clipsieve.config import get_settings
from clipsieve_xhs.api_runner import XhsApiRunner
from clipsieve_xhs.mapping import map_note
from clipsieve_xhs.settings import get_xhs_settings

SHAPE_KEYS = ("video_url", "note_url", "title", "desc", "tag_list", "time")


def describe_shape(note: dict) -> str:
    """Key names and non-emptiness only; never a value from the platform."""
    present = {k: bool(note.get(k)) for k in SHAPE_KEYS}
    present["note_url has xsec_token"] = "xsec_token=" in str(note.get("note_url") or "")
    post = map_note(note, [], "probe-salt", "probe-raw-ref", datetime.now(UTC))
    return (
        f"  shape: keys={sorted(note)}\n"
        f"  shape: non-empty={present}\n"
        f"  shape: map_note -> kind={post.kind} url_has_token={'xsec_token=' in post.url} "
        f"title_len={len(post.text.title)}\n"
    )


def main() -> int:
    keyword = sys.argv[1] if len(sys.argv) > 1 else "新加坡搬到上海"
    pages = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    core = get_settings()
    xhs = get_xhs_settings().model_copy(update={"clipsieve_xhs_note_kinds": "video"})
    runner = XhsApiRunner(xhs, cdp_port=core.clipsieve_xhs_chrome_cdp_port)
    health = runner.healthcheck()
    sys.stdout.write(f"health: {health.ok} {health.message}\n")
    if not health.ok:
        return 2
    workdir = Path(tempfile.mkdtemp(prefix="xhs-api-probe-"))
    total_notes = 0
    shape_done = False
    started = time.monotonic()
    for page in range(1, pages + 1):
        t0 = time.monotonic()
        out = runner.search(keyword, page, workdir)
        videos = sum(1 for n in out.notes if n.get("video_url"))
        sys.stdout.write(
            f"page {page}: notes={len(out.notes)} videos={videos} comments={len(out.comments)} "
            f"errors={len(out.errors)} rc={out.returncode} in {time.monotonic() - t0:.1f}s\n"
        )
        for err in out.errors[:3]:
            sys.stdout.write(f"  error: {err[:160]}\n")
        if out.notes and not shape_done:
            sys.stdout.write(describe_shape(out.notes[0]))
            shape_done = True
        total_notes += len(out.notes)
        if out.returncode != 0 or not out.notes:
            break
    elapsed = time.monotonic() - started
    sys.stdout.write(
        f"total: {total_notes} video notes in {elapsed:.0f}s "
        f"({60 * total_notes / max(elapsed, 1):.0f}/min)\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
