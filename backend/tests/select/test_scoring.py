from pathlib import Path

import pytest

from clipsieve.judge.rubric import load_pack
from clipsieve.models import JudgeAnswer, JudgeResult
from clipsieve.select.scoring import (
    answer_confidence,
    composite,
    needs_review,
    normalize_score,
    passes_hard_filters,
)

RUBRICS = Path(__file__).resolve().parents[3] / "rubrics"
LEG0 = {str(i): f"L{i}" for i in range(5)}
LEG1 = {str(i): f"L{i}" for i in range(1, 6)}


def sc(value, conf=0.9, legend=LEG0):
    return JudgeAnswer(type="score", value=value, confidence=conf, probabilities={}, legend=legend)


def ch(value, conf=0.9):
    return JudgeAnswer(type="choice", value=value, confidence=conf, probabilities={value: conf})


def nl(p):
    return JudgeAnswer(type="noul", value=p)


def result(answers, post_id="local:x"):
    return JudgeResult(
        post_id=post_id,
        pass_name="pass_two",
        model="jev",
        input_tokens=1,
        latency_ms=1,
        answers=answers,
    )


@pytest.mark.parametrize(
    ("value", "legend", "expected"),
    [
        (0.0, LEG0, 0.0),
        (4.0, LEG0, 1.0),
        (2.0, LEG0, 0.5),
        (1.0, LEG1, 0.0),
        (5.0, LEG1, 1.0),
        (3.0, LEG1, 0.5),
        (2.0, None, 0.5),
        (-1.0, LEG0, 0.0),
        (9.0, LEG0, 1.0),
    ],
)
def test_normalize_score(value, legend, expected):
    assert normalize_score(sc(value, legend=legend), 5) == pytest.approx(expected)


def test_normalize_score_needs_two_levels():
    with pytest.raises(ValueError, match="two levels"):
        normalize_score(sc(0.0), 1)


def test_answer_confidence():
    assert answer_confidence(ch("a", 0.7)) == 0.7
    assert answer_confidence(sc(2.0, conf=0.4)) == 0.4
    assert answer_confidence(nl(0.5)) == pytest.approx(0.0)
    assert answer_confidence(nl(0.9)) == pytest.approx(0.8)
    assert answer_confidence(nl(0.1)) == pytest.approx(0.8)


def test_answer_confidence_missing_is_zero():
    assert answer_confidence(JudgeAnswer(type="score", value=1.0)) == 0.0


def test_composite_weights_and_renormalises_over_present_questions():
    pack = load_pack(RUBRICS / "creator-hooks-v1.yaml")
    r = result({"hook_strength": sc(4.0), "persona_fit": sc(2.0), "niche_relevance": sc(0.0)})
    # 0.4*1.0 + 0.4*0.5 + 0.2*0.0 = 0.6
    assert composite(r, pack) == pytest.approx(0.6)
    # missing niche_relevance: renormalise over the other two -> 0.75
    r2 = result({"hook_strength": sc(4.0), "persona_fit": sc(2.0)})
    assert composite(r2, pack) == pytest.approx(0.75)
    # override weights
    assert composite(r, pack, weights={"hook_strength": 1.0}) == pytest.approx(1.0)
    # restrict to question ids (pass one)
    r3 = result({"niche_relevance": sc(4.0), "format_guess": ch("vlog_montage")})
    assert composite(r3, pack, question_ids={"niche_relevance", "format_guess"}) == pytest.approx(
        1.0
    )


def test_composite_with_noul_weight_uses_probability():
    pack = load_pack(RUBRICS / "creator-hooks-v1.yaml")
    r = result({"risky_claim": nl(0.25)})
    assert composite(r, pack, weights={"risky_claim": 1.0}) == pytest.approx(0.25)


def test_composite_no_scorable_answers_is_zero():
    pack = load_pack(RUBRICS / "creator-hooks-v1.yaml")
    assert composite(result({"hook_type": ch("story")}), pack) == 0.0


def test_composite_zero_total_weight_is_zero():
    pack = load_pack(RUBRICS / "creator-hooks-v1.yaml")
    r = result({"hook_strength": sc(4.0)})
    assert composite(r, pack, weights={"hook_strength": 0.0}) == 0.0


def test_composite_on_real_fixture():
    import json

    pack = load_pack(RUBRICS / "creator-hooks-v1.yaml")
    fx = Path(__file__).resolve().parents[1] / "fixtures" / "judge" / "local__fx-001.pass_two.json"
    r = JudgeResult.model_validate(json.loads(fx.read_text(encoding="utf-8")))
    assert 0.0 < composite(r, pack) <= 1.0
    assert passes_hard_filters(r, pack) in (True, False)


def test_hard_filters():
    pack = load_pack(RUBRICS / "creator-hooks-v1.yaml")
    assert passes_hard_filters(result({"risky_claim": nl(0.5)}), pack) is True
    assert passes_hard_filters(result({"risky_claim": nl(0.51)}), pack) is False
    assert passes_hard_filters(result({}), pack) is True  # no answer, no filter


def test_needs_review_only_over_weighted_questions():
    pack = load_pack(RUBRICS / "creator-hooks-v1.yaml")
    ok = result(
        {
            "hook_strength": sc(3.0, 0.9),
            "persona_fit": sc(3.0, 0.6),
            "niche_relevance": sc(3.0, 0.5),
            "hook_type": ch("story", 0.1),
        }
    )
    assert needs_review(ok, pack) is False  # hook_type unweighted; 0.5 is not below 0.5
    low = result(
        {
            "hook_strength": sc(3.0, 0.49),
            "persona_fit": sc(3.0, 0.9),
            "niche_relevance": sc(3.0, 0.9),
        }
    )
    assert needs_review(low, pack) is True
    # explicit weights restrict which questions are checked
    assert needs_review(low, pack, weights={"persona_fit": 1.0}) is False
