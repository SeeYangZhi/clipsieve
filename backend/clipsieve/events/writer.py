"""Append-only JSONL event writer. One writer per run per process."""

from __future__ import annotations

import os
from datetime import UTC, datetime

from pydantic import ValidationError

from clipsieve.events.payloads import PAYLOAD_MODELS
from clipsieve.events.reader import read_events
from clipsieve.logging import get_logger
from clipsieve.models import RunEvent, RunEventType, Stage
from clipsieve.store.paths import RunPaths

log = get_logger(__name__)


class EventWriter:
    def __init__(self, paths: RunPaths, run_id: str) -> None:
        self.paths = paths
        self.run_id = run_id
        self.paths.root.mkdir(parents=True, exist_ok=True)
        self._repair_partial_tail()
        events = read_events(paths)
        self._last_seq = events[-1].seq if events else 0

    def _repair_partial_tail(self) -> None:
        """Terminate a line a dead writer left unfinished, so the next event gets its own line."""
        f = self.paths.events_jsonl
        if not f.exists():
            return
        with f.open("rb") as fh:
            size = fh.seek(0, os.SEEK_END)
            if size == 0:
                return
            fh.seek(size - 1)
            if fh.read(1) == b"\n":
                return
        self._append(b"\n")
        log.warning("events.repaired_partial_line", run_id=self.run_id, offset=size)

    def _append(self, data: bytes) -> None:
        """Append data and fsync. On any failure, cut the file back to its old size and re-raise."""
        with self.paths.events_jsonl.open("ab", buffering=0) as fh:
            start = fh.seek(0, os.SEEK_END)
            try:
                view = memoryview(data)
                while view:
                    view = view[fh.write(view) :]
                os.fsync(fh.fileno())
            except BaseException:
                try:
                    fh.truncate(start)
                except OSError:
                    log.warning("events.truncate_failed", run_id=self.run_id, offset=start)
                raise

    @property
    def last_seq(self) -> int:
        return self._last_seq

    def emit(self, type: RunEventType | str, stage: Stage | str, payload: dict) -> RunEvent:
        etype = RunEventType(type)
        model = PAYLOAD_MODELS[etype]
        try:
            validated = model.model_validate(payload)
        except ValidationError as exc:
            raise ValueError(
                f"payload for {etype.value} does not match {model.__name__}: {exc}"
            ) from exc
        event = RunEvent(
            run_id=self.run_id,
            seq=self._last_seq + 1,
            ts=datetime.now(UTC),
            type=etype,
            stage=Stage(stage),
            payload=validated.model_dump(mode="json", by_alias=True),
        )
        self._append((event.model_dump_json(by_alias=True) + "\n").encode("utf-8"))
        self._last_seq = event.seq
        return event
