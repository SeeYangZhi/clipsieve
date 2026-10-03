"""Load rubric packs and translate questions to and from TypeSafe primitives."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml
from typesafe_sdk import Choice, Noul, Score

from clipsieve.models import (
    ChoiceQuestion,
    JudgeAnswer,
    NoulQuestion,
    Question,
    RubricPack,
    ScoreQuestion,
)

PASS_ONE = "pass_one"
PASS_TWO = "pass_two"
PERSONA_FIT = "persona_fit"
PERSONA_LEVELS = 5
_PACK_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


class PackNotFound(Exception):
    pass


# What `load_pack` raises for a file that is not a valid pack: bad YAML, or data that fails the
# schema or the cross-field rules (pydantic's ValidationError is a ValueError).
PACK_LOAD_ERRORS: tuple[type[Exception], ...] = (ValueError, yaml.YAMLError)


def load_pack(path: Path) -> RubricPack:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    pack = RubricPack.model_validate(data)
    _check_references(pack)
    return pack


def _check_references(pack: RubricPack) -> None:
    """Enforce the cross-field rules in rubrics/AGENTS.md that the JSON Schema cannot express."""
    missing = [q for q in pack.metadata_pass if q not in pack.questions]
    if missing:
        raise ValueError(f"metadata_pass references unknown questions: {missing}")
    bad_weights = [
        q
        for q in pack.selection.weights
        if not isinstance(pack.questions.get(q), ScoreQuestion | NoulQuestion)
    ]
    if bad_weights:
        raise ValueError(f"selection.weights must name score or noul questions: {bad_weights}")
    bad_diversity = [
        q for q in pack.selection.diversity if not isinstance(pack.questions.get(q), ChoiceQuestion)
    ]
    if bad_diversity:
        raise ValueError(f"selection.diversity must name choice questions: {bad_diversity}")


def find_pack(name: str, rubrics_dir: Path) -> RubricPack:
    if not _PACK_NAME.fullmatch(name):
        raise PackNotFound(f"invalid rubric pack name {name!r}")
    path = rubrics_dir / f"{name}.yaml"
    if not path.is_file():
        raise PackNotFound(f"no rubric pack named {name!r} in {rubrics_dir}")
    try:
        return load_pack(path)
    except PACK_LOAD_ERRORS as exc:  # a sidecar such as `<pack>.zh-examples.yaml`, or a broken pack
        raise PackNotFound(f"{path.name} is not a rubric pack: {exc}") from exc


def questions_for_pass(pack: RubricPack, pass_name: str) -> dict[str, Question]:
    if pass_name == PASS_ONE:
        return {q: pack.questions[q] for q in pack.metadata_pass}
    if pass_name == PASS_TWO:
        return dict(pack.questions)
    raise ValueError(f"unknown pass {pass_name!r}")


def to_typesafe(question: Question) -> Choice | Score | Noul:
    if isinstance(question, ChoiceQuestion):
        return Choice(instructions=question.instructions, criteria=dict(question.criteria))
    if isinstance(question, ScoreQuestion):
        return Score(instructions=question.instructions, criteria=list(question.criteria))
    if isinstance(question, NoulQuestion):
        return Noul(instructions=question.instructions)
    raise TypeError(f"unsupported question {type(question)!r}")


def from_typesafe(question_id: str, question: Question, response: Any) -> JudgeAnswer:
    """Map one answer of a `typesafe_sdk.SystemOneResponse` (or a look-alike) to a `JudgeAnswer`.

    Score legend and probability keys arrive as integer levels from 0; they are stored as strings.
    """
    if isinstance(question, ChoiceQuestion):
        a = response.choices[question_id]
        return JudgeAnswer(
            type="choice",
            value=str(a.choice),
            probabilities={str(k): float(v) for k, v in dict(a.probabilities).items()},
            confidence=float(a.confidence),
        )
    if isinstance(question, ScoreQuestion):
        s = response.scores[question_id]
        return JudgeAnswer(
            type="score",
            value=float(s.score),
            probabilities={str(k): float(v) for k, v in dict(s.probabilities).items()},
            confidence=float(s.confidence),
            legend={str(k): _text(v) for k, v in dict(s.legend).items()},
        )
    if isinstance(question, NoulQuestion):
        n = response.nouls[question_id]
        return JudgeAnswer(type="noul", value=float(n.noul))
    raise TypeError(f"unsupported question {type(question)!r}")


def _text(value: Any) -> str:
    """Legend entries echo level descriptions; the SDK allows JSON objects, so keep them JSON."""
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def with_persona_criteria(pack: RubricPack, criteria: list[str]) -> RubricPack:
    if len(criteria) != PERSONA_LEVELS:
        raise ValueError(f"persona_fit needs exactly {PERSONA_LEVELS} levels, got {len(criteria)}")
    q = pack.questions.get(PERSONA_FIT)
    if not isinstance(q, ScoreQuestion):
        raise ValueError("persona_fit must be a score question")
    new_pack = pack.model_copy(deep=True)
    new_pack.questions[PERSONA_FIT] = ScoreQuestion(
        type="score", instructions=q.instructions, criteria=list(criteria)
    )
    return new_pack
