"""File layout of one run under data/runs/<run_id>/. Files are canonical; SQLite indexes them."""

from __future__ import annotations

import re
from pathlib import Path

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


def safe_post_filename(post_id: str) -> str:
    """'youtube:abc' -> 'youtube__abc'. Any other unsafe character becomes '_'."""
    platform, sep, rest = post_id.partition(":")
    if not sep:
        return _UNSAFE.sub("_", post_id)
    return f"{_UNSAFE.sub('_', platform)}__{_UNSAFE.sub('_', rest)}"


class RunPaths:
    def __init__(self, data_dir: Path, run_id: str) -> None:
        self.data_dir = Path(data_dir)
        self.run_id = run_id
        self.root = self.data_dir / "runs" / run_id

    @property
    def run_json(self) -> Path:
        return self.root / "run.json"

    @property
    def plan_json(self) -> Path:
        return self.root / "plan.json"

    @property
    def events_jsonl(self) -> Path:
        return self.root / "events.jsonl"

    @property
    def report_json(self) -> Path:
        return self.root / "report.json"

    @property
    def selection_json(self) -> Path:
        return self.root / "selection.json"

    def post_json(self, post_id: str) -> Path:
        return self.root / "posts" / f"{safe_post_filename(post_id)}.json"

    def raw_path(self, post_id: str, ext: str) -> Path:
        return self.root / "raw" / f"{safe_post_filename(post_id)}.{ext.lstrip('.')}"

    def media_dir(self, post_id: str) -> Path:
        return self.root / "media" / safe_post_filename(post_id)

    def evidence_json(self, post_id: str) -> Path:
        return self.root / "evidence" / f"{safe_post_filename(post_id)}.json"

    def judge_json(self, post_id: str, pass_name: str) -> Path:
        return self.root / "judge" / f"{safe_post_filename(post_id)}.{pass_name}.json"

    def ensure(self) -> None:
        for sub in ["posts", "raw", "media", "evidence", "judge"]:
            (self.root / sub).mkdir(parents=True, exist_ok=True)
