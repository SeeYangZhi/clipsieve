"""`GET /api/runs/{id}/events`: the run's events.jsonl as Server-Sent Events.

Each event is `id: <seq>`, `event: run_event`, `data: <RunEvent JSON>`; the data line is the
events.jsonl line byte for byte (same `by_alias`, `exclude_none` dump, CJK literal). The stream
holds exactly the events with `seq > after` (or `> Last-Event-ID` when a reconnecting
EventSource sends a later one). A finished run (`done`, or stage `failed`) is served whole and
the stream closes; a live one is followed until its first terminal event.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Header, Query
from fastapi.responses import StreamingResponse

from clipsieve.api.runs import Ctx, get_run_or_404
from clipsieve.events.reader import follow_events, read_events
from clipsieve.models import RunEvent, RunEventType, Stage

router = APIRouter()
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def format_sse(event: RunEvent) -> str:
    data = event.model_dump_json(by_alias=True, exclude_none=True)
    return f"id: {event.seq}\nevent: run_event\ndata: {data}\n\n"


def _terminal(event: RunEvent) -> bool:
    return event.type == RunEventType.done or event.stage == Stage.failed


@router.get("/runs/{run_id}/events", response_model_exclude_none=True)
async def events(
    run_id: str,
    ctx: Ctx,
    after: Annotated[int, Query(ge=0)] = 0,
    last_event_id: Annotated[int | None, Header(ge=0)] = None,
) -> StreamingResponse:
    get_run_or_404(ctx, run_id)
    paths = ctx.repo.paths(run_id)
    start = max(after, last_event_id or 0)

    async def stream() -> AsyncIterator[str]:
        existing = read_events(paths)
        last = start
        for event in existing:
            if event.seq > start:
                yield format_sse(event)
                last = event.seq
        if any(_terminal(e) for e in existing):
            return  # finished: everything after `start` was sent, including any later reselect
        async for event in follow_events(paths, after=last):
            yield format_sse(event)

    return StreamingResponse(stream(), media_type="text/event-stream", headers=SSE_HEADERS)
