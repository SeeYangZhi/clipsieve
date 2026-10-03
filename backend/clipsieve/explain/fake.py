"""Fixture-backed explain backend for tests and the Playwright flow."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from clipsieve.explain.base import ExplainBackend, ExplainPacket, RubricPackSummary
from clipsieve.models import Brief, ClipExplanation, Plan, Report


class FakeExplainBackend(ExplainBackend):
    """Replays `<fixture_dir>/explain/plan.json` and `report.json`.

    `plan` keeps a filled-in brief (one with a topic), else the fixture's. `explain` re-points
    every citation at `packet.posts` and writes one clip per packet post, in packet order.
    """

    def __init__(self, fixture_dir: Path) -> None:
        self._dir = Path(fixture_dir) / "explain"
        self.calls: list[str] = []

    def _load(self, name: str) -> dict[str, Any]:
        return json.loads((self._dir / name).read_text(encoding="utf-8"))

    def plan(self, brief: Brief, packs: list[RubricPackSummary], platforms: list[str]) -> Plan:
        self.calls.append("plan")
        plan = Plan.model_validate(self._load("plan.json"))
        return plan.model_copy(update={"brief": brief if brief.topic else plan.brief})

    def explain(self, packet: ExplainPacket) -> Report:
        self.calls.append("explain")
        report = Report.model_validate(self._load("report.json"))
        ids = [p.id for p in packet.posts]
        if not ids:
            return report.model_copy(
                update={"patterns": [], "clips": [], "gaps": [], "concepts": []}
            )

        def remap(cited: list[str]) -> list[str]:
            out = [pid if pid in ids else ids[i % len(ids)] for i, pid in enumerate(cited)]
            return list(dict.fromkeys(out))

        template = (
            report.clips[0]
            if report.clips
            else ClipExplanation(post_id="", why_it_works="", hook_quote="", weaknesses="")
        )
        clips = [
            (report.clips[i] if i < len(report.clips) else template).model_copy(
                update={"post_id": pid}
            )
            for i, pid in enumerate(ids)
        ]
        return report.model_copy(
            update={
                "patterns": [
                    p.model_copy(update={"post_ids": remap(p.post_ids)}) for p in report.patterns
                ],
                "clips": clips,
                "gaps": [g.model_copy(update={"post_ids": remap(g.post_ids)}) for g in report.gaps],
                "concepts": [
                    c.model_copy(update={"inspired_by_post_ids": remap(c.inspired_by_post_ids)})
                    for c in report.concepts
                ],
            }
        )
