from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from structlog.testing import capture_logs

from clipsieve.events import writer as writer_module
from clipsieve.events.reader import follow_events, read_events
from clipsieve.events.writer import EventWriter
from clipsieve.models import Post
from clipsieve.store.paths import RunPaths

BRIEF = {"text": "b", "topic": "t", "audience": "a", "persona": "p"}
COUNTERS = {
    "collected": 1,
    "pass_one_kept": 1,
    "judged": 1,
    "shortlisted": 1,
    "review": 0,
    "errors": 0,
    "jev_input_tokens": 1800,
    "jev_cost_usd": 0.0000756,
    "elapsed_s": 12.5,
}


@pytest.fixture
def paths(data_dir: Path) -> RunPaths:
    p = RunPaths(data_dir, "run_ev")
    p.ensure()
    return p


def test_emit_assigns_seq_and_appends_lines(paths: RunPaths):
    w = EventWriter(paths, "run_ev")
    e1 = w.emit(
        "run_created",
        "planning",
        {"brief": BRIEF, "platforms": ["local"], "quantities": {"local": 5}},
    )
    e2 = w.emit("stage_changed", "collecting", {"from": "planning", "to": "collecting"})
    assert (e1.seq, e2.seq) == (1, 2)
    assert w.last_seq == 2
    lines = paths.events_jsonl.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[1])["payload"] == {"from": "planning", "to": "collecting"}


def test_emit_rejects_bad_payload(paths: RunPaths):
    w = EventWriter(paths, "run_ev")
    with pytest.raises(ValueError):
        w.emit("error", "collecting", {"message": "no where field"})
    assert not paths.events_jsonl.exists() or paths.events_jsonl.read_text() == ""


def test_seq_continues_after_restart(paths: RunPaths):
    w = EventWriter(paths, "run_ev")
    w.emit(
        "run_created",
        "planning",
        {"brief": BRIEF, "platforms": ["local"], "quantities": {"local": 5}},
    )
    w.emit("stage_changed", "collecting", {"from": "planning", "to": "collecting"})
    w2 = EventWriter(paths, "run_ev")
    assert w2.last_seq == 2
    e3 = w2.emit(
        "error", "collecting", {"where": "adapter.local", "message": "boom", "recoverable": True}
    )
    assert e3.seq == 3


def test_read_events_after_is_exact(paths: RunPaths):
    w = EventWriter(paths, "run_ev")
    for i in range(5):
        w.emit("error", "collecting", {"where": "x", "message": str(i), "recoverable": True})
    got = read_events(paths, after=2)
    assert [e.seq for e in got] == [3, 4, 5]
    assert read_events(paths, after=5) == []
    assert [e.seq for e in read_events(paths)] == [1, 2, 3, 4, 5]


def test_post_collected_payload_keeps_cjk(paths: RunPaths, fixtures_dir: Path):
    post = Post.model_validate_json(
        (fixtures_dir / "posts/local__fx-003.json").read_text(encoding="utf-8")
    )
    w = EventWriter(paths, "run_ev")
    w.emit("post_collected", "collecting", {"post": post.model_dump(mode="json")})
    raw = paths.events_jsonl.read_text(encoding="utf-8")
    assert "上海超市物价大公开" in raw
    ev = read_events(paths)[0]
    assert ev.payload["post"]["text"]["title"] == "上海超市物价大公开 🇸🇬→🇨🇳"


async def test_follow_events_tails_and_stops_on_done(paths: RunPaths):
    w = EventWriter(paths, "run_ev")
    w.emit(
        "run_created",
        "planning",
        {"brief": BRIEF, "platforms": ["local"], "quantities": {"local": 1}},
    )
    seen: list[int] = []

    async def consume():
        async for ev in follow_events(paths, after=0, poll_s=0.02):
            seen.append(ev.seq)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.05)
    w.emit("stage_changed", "collecting", {"from": "planning", "to": "collecting"})
    await asyncio.sleep(0.05)
    w.emit("done", "done", {"counters": COUNTERS})
    await asyncio.wait_for(task, timeout=2.0)
    assert seen == [1, 2, 3]


async def test_follow_events_stops_on_failed_stage(paths: RunPaths):
    w = EventWriter(paths, "run_ev")
    w.emit("error", "failed", {"where": "explain", "message": "twice", "recoverable": False})
    seen = [ev.seq async for ev in follow_events(paths, after=0, poll_s=0.02)]
    assert seen == [1]


async def test_follow_events_ignores_partial_trailing_line(paths: RunPaths):
    w = EventWriter(paths, "run_ev")
    w.emit(
        "run_created",
        "planning",
        {"brief": BRIEF, "platforms": ["local"], "quantities": {"local": 1}},
    )
    with paths.events_jsonl.open("a", encoding="utf-8") as f:
        f.write(
            '{"run_id": "run_ev", "seq": 2, "ts": "2026-10-03T00:00:00Z", '
            '"type": "done", "stage": "done", "payload": {"counters": '
        )
        f.flush()
    seen: list[int] = []

    async def consume():
        async for ev in follow_events(paths, after=0, poll_s=0.02):
            seen.append(ev.seq)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.08)
    assert seen == [1]
    with paths.events_jsonl.open("a", encoding="utf-8") as f:
        f.write(json.dumps(COUNTERS) + "}}\n")
    await asyncio.wait_for(task, timeout=2.0)
    assert seen == [1, 2]


async def test_readers_skip_partial_line_split_mid_codepoint(paths: RunPaths):
    """A writer caught mid-append can leave half of a multibyte character at the end of the file."""
    w = EventWriter(paths, "run_ev")
    w.emit("error", "collecting", {"where": "x", "message": "上海", "recoverable": True})
    event = {
        "run_id": "run_ev",
        "seq": 2,
        "ts": "2026-10-03T00:00:00Z",
        "type": "error",
        "stage": "failed",
        "payload": {"where": "x", "message": "上海", "recoverable": False},
    }
    raw = json.dumps(event, ensure_ascii=False).encode("utf-8") + b"\n"
    cut = raw.index("上".encode()) + 1
    with paths.events_jsonl.open("ab") as f:
        f.write(raw[:cut])
    with capture_logs() as logs:
        assert [e.seq for e in read_events(paths)] == [1]
    assert logs == []  # a trailing partial line is not corrupt, just unfinished
    seen: list[int] = []

    async def consume():
        async for ev in follow_events(paths, after=0, poll_s=0.02):
            seen.append(ev.seq)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.08)
    assert seen == [1]
    with paths.events_jsonl.open("ab") as f:
        f.write(raw[cut:])
    await asyncio.wait_for(task, timeout=2.0)
    assert seen == [1, 2]
    assert [e.payload["message"] for e in read_events(paths)] == ["上海", "上海"]


async def _drain(agen) -> list[int]:
    return [ev.seq async for ev in agen]


def test_writer_repairs_partial_tail_before_appending(paths: RunPaths):
    w = EventWriter(paths, "run_ev")
    w.emit("error", "collecting", {"where": "x", "message": "上海", "recoverable": True})
    fragment = '{"run_id": "run_ev", "seq": 2, "payload": {"message": "上'.encode()[:-1]
    with paths.events_jsonl.open("ab") as f:
        f.write(fragment)
    with capture_logs() as logs:
        w2 = EventWriter(paths, "run_ev")
    assert w2.last_seq == 1
    assert [entry["event"] for entry in logs] == [
        "events.repaired_partial_line",
        "events.skip_corrupt_line",
    ]
    e2 = w2.emit("stage_changed", "collecting", {"from": "planning", "to": "collecting"})
    assert e2.seq == 2
    assert [(e.seq, e.type) for e in read_events(paths)] == [(1, "error"), (2, "stage_changed")]
    lines = paths.events_jsonl.read_bytes().split(b"\n")
    assert lines[1] == fragment
    assert lines[-1] == b""


def test_emit_truncates_failed_write(paths: RunPaths, monkeypatch: pytest.MonkeyPatch):
    w = EventWriter(paths, "run_ev")
    w.emit("error", "collecting", {"where": "x", "message": "one", "recoverable": True})
    before = paths.events_jsonl.read_bytes()

    def no_space(fd: int) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(writer_module.os, "fsync", no_space)
    with pytest.raises(OSError):
        w.emit("error", "collecting", {"where": "x", "message": "two", "recoverable": True})
    monkeypatch.undo()
    assert paths.events_jsonl.read_bytes() == before
    assert w.last_seq == 1
    e2 = w.emit("error", "collecting", {"where": "x", "message": "three", "recoverable": True})
    assert e2.seq == 2
    assert [(e.seq, e.payload["message"]) for e in read_events(paths)] == [(1, "one"), (2, "three")]


async def test_readers_log_corrupt_complete_lines(paths: RunPaths):
    w = EventWriter(paths, "run_ev")
    w.emit("error", "collecting", {"where": "x", "message": "a", "recoverable": True})
    bad_offset = paths.events_jsonl.stat().st_size
    with capture_logs() as logs:
        agen = follow_events(paths, after=0, poll_s=0.02)
        assert (await asyncio.wait_for(anext(agen), timeout=2.0)).seq == 1
        with paths.events_jsonl.open("ab") as f:
            f.write(b'{"not": "an event"}\n')
        w.emit("done", "done", {"counters": COUNTERS})
        assert await asyncio.wait_for(_drain(agen), timeout=2.0) == [2]
        assert [e.seq for e in read_events(paths)] == [1, 2]
    skipped = [(x["event"], x["run_id"], x["offset"]) for x in logs]
    assert skipped == [("events.skip_corrupt_line", "run_ev", bad_offset)] * 2


@pytest.mark.parametrize("terminal", ["done", "failed"])
async def test_follow_events_returns_when_after_reaches_terminal(paths: RunPaths, terminal: str):
    w = EventWriter(paths, "run_ev")
    w.emit("stage_changed", "collecting", {"from": "planning", "to": "collecting"})
    if terminal == "done":
        last = w.emit("done", "done", {"counters": COUNTERS})
    else:
        last = w.emit("stage_changed", "failed", {"from": "explaining", "to": "failed"})
    for after in (last.seq, last.seq + 3):
        agen = follow_events(paths, after=after, poll_s=0.02)
        assert await asyncio.wait_for(_drain(agen), timeout=2.0) == []
    agen = follow_events(paths, after=last.seq - 1, poll_s=0.02)
    assert await asyncio.wait_for(_drain(agen), timeout=2.0) == [last.seq]
