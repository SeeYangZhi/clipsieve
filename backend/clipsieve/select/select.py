"""Selection output model. Plan 03 adds select(), pass_one_keep() and helpers to this module."""

from __future__ import annotations

import math

from pydantic import BaseModel, ConfigDict

from clipsieve.models import JudgeResult, RubricPack
from clipsieve.select.quotas import violates_quota
from clipsieve.select.scoring import composite, needs_review, passes_hard_filters


class Selection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shortlist: list[str]
    review: list[str]
    scores: dict[str, float]
    dropped: dict[str, str]


HARD_FILTER = "hard_filter"
QUOTA = "quota"
NOT_SELECTED = "not_selected"


def _ranked(results: list[JudgeResult], scores: dict[str, float]) -> list[JudgeResult]:
    return sorted(results, key=lambda r: (-scores[r.post_id], r.post_id))


def select(
    results: list[JudgeResult],
    pack: RubricPack,
    weights_override: dict[str, float] | None = None,
) -> Selection:
    scores = {r.post_id: composite(r, pack, weights=weights_override) for r in results}
    dropped: dict[str, str] = {}
    review: list[str] = []
    candidates: list[JudgeResult] = []
    for r in results:
        if not passes_hard_filters(r, pack):
            dropped[r.post_id] = HARD_FILTER
        elif needs_review(r, pack, weights=weights_override):
            review.append(r.post_id)
        else:
            candidates.append(r)
    review.sort(key=lambda pid: (-scores[pid], pid))

    size = pack.selection.shortlist_size
    chosen: list[JudgeResult] = []
    for r in _ranked(candidates, scores):
        if len(chosen) >= size:
            dropped[r.post_id] = NOT_SELECTED
        elif violates_quota(r, chosen, pack, size):
            dropped[r.post_id] = QUOTA
        else:
            chosen.append(r)
    return Selection(
        shortlist=[r.post_id for r in chosen], review=review, scores=scores, dropped=dropped
    )


def pass_one_keep(results: list[JudgeResult], pack: RubricPack) -> set[str]:
    if not results:
        return set()
    qids = set(pack.metadata_pass)
    scores = {r.post_id: composite(r, pack, question_ids=qids) for r in results}
    keep_n = max(1, math.ceil(pack.pass_one_keep * len(results)))
    return {r.post_id for r in _ranked(results, scores)[:keep_n]}
