"""Read and tail a run's events.jsonl."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from pydantic import ValidationError

from clipsieve.logging import get_logger
from clipsieve.models import RunEvent, RunEventType, Stage
from clipsieve.store.paths import RunPaths

log = get_logger(__name__)


def _parse_complete_lines(buf: bytes, run_id: str, start: int = 0) -> tuple[list[RunEvent], bytes]:
    """Parse every newline-terminated line in buf; return events and the unterminated remainder.

    Works on bytes so a line cut inside a multibyte UTF-8 character by a concurrent append is
    held back, silently, until its newline arrives. `start` is the file offset of buf[0]; a
    complete line that does not parse is logged with its offset and skipped.
    """
    events: list[RunEvent] = []
    pos = 0
    while (nl := buf.find(b"\n", pos)) >= 0:
        line = buf[pos:nl].strip()
        if line:
            try:
                events.append(RunEvent.model_validate_json(line))
            except ValidationError:
                log.warning("events.skip_corrupt_line", run_id=run_id, offset=start + pos)
        pos = nl + 1
    return events, buf[pos:]


def read_events(paths: RunPaths, after: int = 0) -> list[RunEvent]:
    f = paths.events_jsonl
    if not f.exists():
        return []
    events, _ = _parse_complete_lines(f.read_bytes(), paths.run_id)
    return [e for e in events if e.seq > after]


def _is_terminal(event: RunEvent) -> bool:
    return event.type == RunEventType.done or event.stage == Stage.failed


async def follow_events(
    paths: RunPaths, after: int = 0, poll_s: float = 0.25
) -> AsyncIterator[RunEvent]:
    """Yield events with seq > after as they are appended.

    Returns at the first terminal event in the file (a done event or any event whose stage is
    failed), whether or not `after` filtered it out, so a client that reconnects after the run
    finished gets an empty stream instead of a hang.
    """
    f = paths.events_jsonl
    offset = 0  # bytes read from the file so far
    remainder = b""
    last = after
    while True:
        if f.exists():
            with f.open("rb") as fh:
                fh.seek(offset)
                chunk = fh.read()
            start = offset - len(remainder)
            offset += len(chunk)
            events, remainder = _parse_complete_lines(remainder + chunk, paths.run_id, start)
            for ev in events:
                if ev.seq > last:
                    last = ev.seq
                    yield ev
                if _is_terminal(ev):
                    return
        await asyncio.sleep(poll_s)
