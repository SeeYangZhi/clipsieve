"""Diversity quotas over choice answers."""

from __future__ import annotations

import math

from clipsieve.models import ChoiceQuestion, JudgeResult, RubricPack


def _label(result: JudgeResult, qid: str) -> str | None:
    answer = result.answers.get(qid)
    if answer is None or answer.type != "choice":
        return None
    return str(answer.value)


def violates_quota(
    candidate: JudgeResult, chosen: list[JudgeResult], pack: RubricPack, shortlist_size: int
) -> bool:
    """True when adding candidate would push a diversity label above max_share of shortlist_size."""
    for qid, rule in pack.selection.diversity.items():
        if not isinstance(pack.questions.get(qid), ChoiceQuestion):
            continue
        label = _label(candidate, qid)
        if label is None:
            continue
        same = sum(1 for c in chosen if _label(c, qid) == label)
        # A label may always appear once, so tiny shortlists stay fillable.
        cap = max(1, math.floor(rule.max_share * shortlist_size + 1e-9))
        if same + 1 > cap:
            return True
    return False
