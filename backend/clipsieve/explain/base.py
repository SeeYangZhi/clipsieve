"""Explain backend contract: planning a run and explaining a shortlist.

Backends never know the run id: they return `Plan.run_id` / `Report.run_id` as they have them
and the caller overwrites both. Prompts in `PROMPTS_DIR` describe the task only; policy
(weights, thresholds, quotas) stays in rubric pack YAML and code.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import AwareDatetime, BaseModel, ConfigDict, model_validator

from clipsieve.config import Settings
from clipsieve.models import (
    Brief,
    Evidence,
    JudgeResult,
    Kind,
    Media,
    Metrics,
    Plan,
    Platform,
    Post,
    PostText,
    Report,
)

PROMPTS_DIR = Path(__file__).parent / "prompts"


class RubricPackSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    description: str
    question_ids: list[str]


class ExplainPost(BaseModel):
    """A shortlisted `Post` as the explain step sees it: every `Post` field except the raw
    `comments` (the evidence `comment_summary` carries counts, top terms and a sample).

    A `Post` instance validates into one, so `ExplainPacket(posts=[post, ...])` drops comments.
    `tests/explain/test_base.py` keeps the fields in step with the generated `Post`.
    """

    model_config = ConfigDict(extra="forbid")
    id: str
    platform: Platform
    url: str
    creator_hash: str
    creator_display: str | None = None
    posted_at: AwareDatetime | None = None
    kind: Kind
    text: PostText
    media: list[Media]
    metrics: Metrics
    lang: str | None = None
    raw_ref: str
    collected_at: AwareDatetime

    @model_validator(mode="before")
    @classmethod
    def _from_post(cls, data: Any) -> Any:
        if isinstance(data, Post):
            return data.model_dump(exclude={"comments"})
        return data


class ExplainPacket(BaseModel):
    """Everything the explain step sees, keyed by post id where per-post."""

    model_config = ConfigDict(extra="forbid")
    brief: Brief
    posts: list[ExplainPost]
    evidence: dict[str, Evidence]
    judge: dict[str, JudgeResult]
    aggregates: dict[str, dict[str, int]]
    keyframes: dict[str, list[str]]


class PlanRequest(BaseModel):
    """The serialised planner input."""

    model_config = ConfigDict(extra="forbid")
    brief: Brief
    packs: list[RubricPackSummary]
    platforms: list[str]


class ExplainError(Exception):
    pass


class ExplainBackend(Protocol):
    def plan(self, brief: Brief, packs: list[RubricPackSummary], platforms: list[str]) -> Plan: ...

    def explain(self, packet: ExplainPacket) -> Report: ...


def validate_report_citations(report: Report, known_post_ids: set[str]) -> list[str]:
    """Return every cited post id not in `known_post_ids`, sorted and unique."""
    cited: set[str] = set()
    for p in report.patterns:
        cited.update(p.post_ids)
    for c in report.clips:
        cited.add(c.post_id)
    for g in report.gaps:
        cited.update(g.post_ids)
    for k in report.concepts:
        cited.update(k.inspired_by_post_ids)
    return sorted(cited - known_post_ids)


def cli_payload(mode: Literal["plan", "explain"], body: BaseModel) -> str:
    """JSON for the CLI's stdin: `body` plus a top-level `mode`, the only non-schema key.

    Optional means absent (`exclude_none`); `ensure_ascii=False` keeps CJK text literal.
    """
    data = body.model_dump(mode="json", exclude_none=True, by_alias=True)
    if "mode" in data:
        raise ExplainError("payload body must not carry its own 'mode' key")
    return json.dumps({"mode": mode, **data}, ensure_ascii=False)


def get_backend(settings: Settings, fixture_dir: Path | None = None) -> ExplainBackend:
    kind = settings.clipsieve_explain_backend
    if kind == "fake":
        from clipsieve.explain.fake import FakeExplainBackend

        if fixture_dir is None:
            raise ExplainError("fake explain backend needs fixture_dir")
        return FakeExplainBackend(fixture_dir)
    if kind == "claude_cli":
        from clipsieve.explain.claude_cli import ClaudeCliBackend

        return ClaudeCliBackend(
            bin=settings.clipsieve_claude_bin,
            max_budget_usd=settings.clipsieve_claude_max_budget_usd,
        )
    if kind == "claude_api":
        from clipsieve.explain.claude_api import ClaudeApiBackend

        return ClaudeApiBackend(api_key=settings.anthropic_api_key)
    raise ExplainError(f"unknown explain backend {kind!r}")
