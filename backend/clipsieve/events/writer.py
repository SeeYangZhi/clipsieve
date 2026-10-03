"""Append-only JSONL event writer. One writer per run per process."""

from __future__ import annotations

import os
from datetime import UTC, datetime

from pydantic import ValidationError

from clipsieve.events.payloads import PAYLOAD_MODELS
from clipsieve.logging import get_logger
from clipsieve.models import RunEvent, RunEventType, Stage
from clipsieve.store.paths import RunPaths

log = get_logger(__name__)


class EventWriter:
    def __init__(self, paths: RunPaths, run_id: str) -> None:
        self.paths = paths
        self.run_id = run_id
        self.paths.root.mkdir(parents=True, exist_ok=True)
        self._last_seq = self._read_last_seq()

    def _read_last_seq(self) -> int:
        f = self.paths.events_jsonl
        if not f.exists():
            return 0
        last = 0
        # Bytes, not text: a trailing line cut mid-codepoint must not abort the resume scan.
        with f.open("rb") as fh:
            for raw in fh:
                line = raw.strip()
                if not line:
                    continue
                try:
                    last = RunEvent.model_validate_json(line).seq
                except ValidationError:
                    log.warning("events.skip_corrupt_line", run_id=self.run_id)
        return last

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
        line = event.model_dump_json(by_alias=True) + "\n"
        with self.paths.events_jsonl.open("a", encoding="utf-8") as fh:
            fh.write(line)
            fh.flush()
            os.fsync(fh.fileno())
        self._last_seq = event.seq
        return event
