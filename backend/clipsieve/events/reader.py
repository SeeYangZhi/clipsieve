"""Read and tail a run's events.jsonl."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from pydantic import ValidationError

from clipsieve.models import RunEvent, RunEventType, Stage
from clipsieve.store.paths import RunPaths


def _parse_complete_lines(buf: bytes) -> tuple[list[RunEvent], bytes]:
    """Parse every newline-terminated line in buf; return events and the unterminated remainder.

    Works on bytes so a line cut inside a multibyte UTF-8 character by a concurrent append is
    held back until its newline arrives instead of failing to decode.
    """
    *lines, remainder = buf.split(b"\n")
    events: list[RunEvent] = []
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        try:
            events.append(RunEvent.model_validate_json(line))
        except ValidationError:
            continue
    return events, remainder


def read_events(paths: RunPaths, after: int = 0) -> list[RunEvent]:
    f = paths.events_jsonl
    if not f.exists():
        return []
    events, _ = _parse_complete_lines(f.read_bytes())
    return [e for e in events if e.seq > after]


def _is_terminal(event: RunEvent) -> bool:
    return event.type == RunEventType.done or event.stage == Stage.failed


async def follow_events(
    paths: RunPaths, after: int = 0, poll_s: float = 0.25
) -> AsyncIterator[RunEvent]:
    """Yield events with seq > after as they are appended.

    Returns after a done event or an event whose stage is failed.
    """
    f = paths.events_jsonl
    offset = 0
    remainder = b""
    last = after
    while True:
        if f.exists():
            with f.open("rb") as fh:
                fh.seek(offset)
                chunk = fh.read()
            offset += len(chunk)
            events, remainder = _parse_complete_lines(remainder + chunk)
            for ev in events:
                if ev.seq <= last:
                    continue
                last = ev.seq
                yield ev
                if _is_terminal(ev):
                    return
        await asyncio.sleep(poll_s)
