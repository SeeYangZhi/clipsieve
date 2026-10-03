"""Pure scoring helpers over JudgeResults. No I/O, no model calls."""

from __future__ import annotations

from clipsieve.models import JudgeAnswer, JudgeResult, NoulQuestion, RubricPack, ScoreQuestion


def _first_level(answer: JudgeAnswer) -> int:
    """Lowest level index: the minimum integer legend key, or 0 when there is no legend."""
    if answer.legend:
        keys = [int(k) for k in answer.legend if str(k).lstrip("-").isdigit()]
        if keys:
            return min(keys)
    return 0


def normalize_score(answer: JudgeAnswer, levels: int) -> float:
    """Position of a fractional score among `levels` levels, clamped to 0..1."""
    if levels < 2:
        raise ValueError("a score needs at least two levels")
    pos = (float(answer.value) - _first_level(answer)) / (levels - 1)
    return min(1.0, max(0.0, pos))


def answer_confidence(answer: JudgeAnswer) -> float:
    if answer.type == "noul":
        return abs(2.0 * float(answer.value) - 1.0)
    return float(answer.confidence or 0.0)


def _scalar(answer: JudgeAnswer, pack: RubricPack, qid: str) -> float | None:
    question = pack.questions.get(qid)
    if isinstance(question, ScoreQuestion) and answer.type == "score":
        return normalize_score(answer, len(question.criteria))
    if isinstance(question, NoulQuestion) and answer.type == "noul":
        return float(answer.value)
    return None  # choice answers never contribute to the composite


def _effective_weights(
    pack: RubricPack, weights: dict[str, float] | None, question_ids: set[str] | None
) -> dict[str, float]:
    if weights is not None:
        return dict(weights)
    base = dict(pack.selection.weights)
    if question_ids is None:
        return base
    restricted = {q: w for q, w in base.items() if q in question_ids}
    if restricted:
        return restricted
    return dict.fromkeys(question_ids, 1.0)


def composite(
    result: JudgeResult,
    pack: RubricPack,
    weights: dict[str, float] | None = None,
    question_ids: set[str] | None = None,
) -> float:
    """Weighted mean of scalar answers, renormalised over the weighted questions present."""
    eff = _effective_weights(pack, weights, question_ids)
    total_w = 0.0
    acc = 0.0
    for qid, w in eff.items():
        answer = result.answers.get(qid)
        if answer is None:
            continue
        value = _scalar(answer, pack, qid)
        if value is None:
            continue
        acc += w * value
        total_w += w
    return acc / total_w if total_w > 0 else 0.0


def passes_hard_filters(result: JudgeResult, pack: RubricPack) -> bool:
    limit = pack.selection.hard_filters.risky_claim_max
    answer = result.answers.get("risky_claim")
    if limit is None or answer is None:
        return True
    return float(answer.value) <= limit


def needs_review(
    result: JudgeResult, pack: RubricPack, weights: dict[str, float] | None = None
) -> bool:
    threshold = pack.selection.review_confidence_below
    for qid in pack.selection.weights if weights is None else weights:
        answer = result.answers.get(qid)
        if answer is not None and answer_confidence(answer) < threshold:
            return True
    return False
