"""Per-type payload shapes for RunEvent. Mirrors the table in plan 00 (overview)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from clipsieve.models import (
    Brief,
    Counters,
    Evidence,
    JudgeResult,
    Plan,
    Post,
    Report,
    RunEventType,
    Stage,
)


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class RunCreatedPayload(_Payload):
    brief: Brief
    platforms: list[str]
    quantities: dict[str, int]


class PlanPayload(_Payload):
    plan: Plan


class PostCollectedPayload(_Payload):
    post: Post


class PassOneJudgedPayload(_Payload):
    judge: JudgeResult
    kept: bool
    composite: float


class EvidenceReadyPayload(_Payload):
    post_id: str
    evidence: Evidence


class JudgedPayload(_Payload):
    judge: JudgeResult
    composite: float


class SelectedPayload(_Payload):
    shortlist: list[str]
    review: list[str]
    scores: dict[str, float]
    dropped: dict[str, str]


class ExplainedPayload(_Payload):
    report: Report


class ErrorPayload(_Payload):
    where: str
    message: str
    post_id: str | None = None
    recoverable: bool


class StageChangedPayload(_Payload):
    from_: Stage = Field(alias="from")
    to: Stage


class DonePayload(_Payload):
    counters: Counters


PAYLOAD_MODELS: dict[RunEventType, type[BaseModel]] = {
    RunEventType.run_created: RunCreatedPayload,
    RunEventType.plan_ready: PlanPayload,
    RunEventType.plan_approved: PlanPayload,
    RunEventType.post_collected: PostCollectedPayload,
    RunEventType.pass_one_judged: PassOneJudgedPayload,
    RunEventType.evidence_ready: EvidenceReadyPayload,
    RunEventType.judged: JudgedPayload,
    RunEventType.selected: SelectedPayload,
    RunEventType.explained: ExplainedPayload,
    RunEventType.error: ErrorPayload,
    RunEventType.stage_changed: StageChangedPayload,
    RunEventType.done: DonePayload,
}
