"""Per-run pipeline decisions the Runner needs to resume: `<run>/state.json`."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from clipsieve.store.paths import RunPaths


class RunState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pass_one_kept: list[str] = []
    pass_one_dropped: list[str] = []
    judge_failed: list[str] = []
    extracted: list[str] = []


def _path(paths: RunPaths) -> Path:
    return paths.root / "state.json"


def load_state(paths: RunPaths) -> RunState:
    p = _path(paths)
    if not p.exists():
        return RunState()
    return RunState.model_validate_json(p.read_text(encoding="utf-8"))


def save_state(paths: RunPaths, state: RunState) -> None:
    """Temp file then replace, so a crash never leaves a half-written state."""
    target = _path(paths)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(state.model_dump_json(indent=2), encoding="utf-8")
    tmp.replace(target)
