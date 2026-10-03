import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from typesafe_sdk import SystemOneResponse

from clipsieve.judge.rubric import (
    PackNotFound,
    find_pack,
    from_typesafe,
    load_pack,
    questions_for_pass,
    to_typesafe,
    with_persona_criteria,
)
from clipsieve.models import ChoiceQuestion, NoulQuestion, ScoreQuestion

RUBRICS = Path(__file__).resolve().parents[3] / "rubrics"


def test_load_pack_parses_real_yaml():
    pack = load_pack(RUBRICS / "creator-hooks-v1.yaml")
    assert pack.name == "creator-hooks-v1"
    assert pack.jev_model == "jev-1.13.0"
    assert set(pack.questions) == {
        "hook_type",
        "hook_strength",
        "format",
        "persona_fit",
        "risky_claim",
        "niche_relevance",
        "format_guess",
    }
    assert isinstance(pack.questions["hook_type"], ChoiceQuestion)
    assert isinstance(pack.questions["hook_strength"], ScoreQuestion)
    assert isinstance(pack.questions["risky_claim"], NoulQuestion)
    assert len(pack.questions["hook_strength"].criteria) == 5


def test_find_pack_by_name_and_missing():
    assert find_pack("creator-hooks-v1", RUBRICS).version == 1
    with pytest.raises(PackNotFound):
        find_pack("nope", RUBRICS)


def test_questions_for_pass():
    pack = load_pack(RUBRICS / "creator-hooks-v1.yaml")
    assert set(questions_for_pass(pack, "pass_one")) == {"niche_relevance", "format_guess"}
    assert set(questions_for_pass(pack, "pass_two")) == set(pack.questions)
    with pytest.raises(ValueError):
        questions_for_pass(pack, "pass_three")


def test_to_typesafe_shapes():
    pack = load_pack(RUBRICS / "creator-hooks-v1.yaml")
    choice = to_typesafe(pack.questions["hook_type"])
    score = to_typesafe(pack.questions["hook_strength"])
    noul = to_typesafe(pack.questions["risky_claim"])
    assert type(choice).__name__ == "Choice"
    assert type(score).__name__ == "Score"
    assert type(noul).__name__ == "Noul"
    assert "curiosity_gap" in choice.criteria
    assert len(score.criteria) == 5


def test_from_typesafe_maps_each_primitive():
    pack = load_pack(RUBRICS / "creator-hooks-v1.yaml")
    response = SimpleNamespace(
        choices={
            "hook_type": SimpleNamespace(
                choice="story", probabilities={"story": 0.7, "none": 0.3}, confidence=0.53
            )
        },
        scores={
            "hook_strength": SimpleNamespace(
                score=3.2,
                legend={"0": "a", "1": "b", "2": "c", "3": "d", "4": "e"},
                probabilities={"3": 0.8, "4": 0.2},
                confidence=0.75,
            )
        },
        nouls={"risky_claim": SimpleNamespace(noul=0.12)},
    )
    a = from_typesafe("hook_type", pack.questions["hook_type"], response)
    assert a.type.value == "choice" and a.value == "story" and a.confidence == 0.53
    b = from_typesafe("hook_strength", pack.questions["hook_strength"], response)
    assert b.type.value == "score" and b.value == 3.2 and b.legend["4"] == "e"
    c = from_typesafe("risky_claim", pack.questions["risky_claim"], response)
    assert c.type.value == "noul" and c.value == 0.12 and c.confidence is None


def test_with_persona_criteria_requires_five():
    pack = load_pack(RUBRICS / "creator-hooks-v1.yaml")
    new = with_persona_criteria(pack, ["a", "b", "c", "d", "e"])
    assert new.questions["persona_fit"].criteria == ["a", "b", "c", "d", "e"]
    assert (
        pack.questions["persona_fit"].criteria[0] == "Unrelated creator and situation"
    )  # original untouched
    with pytest.raises(ValueError):
        with_persona_criteria(pack, ["only", "four", "levels", "here"])


# --- beyond the brief: real SDK response, path guard, pack contracts, no aliasing ---


def test_from_typesafe_reads_real_sdk_response():
    """The installed SDK keys score legend/probabilities by int; JudgeAnswer keys are "0".."4"."""
    pack = load_pack(RUBRICS / "creator-hooks-v1.yaml")
    payload = {
        "model": "jev-1.13.0",
        "usage": {"input_tokens": 120, "output_tokens": 4},
        "answers": {
            "hook_type": {
                "type": "choice",
                "choice": "story",
                "confidence": 0.53,
                "probabilities": {"story": 0.7, "none": 0.3},
            },
            "hook_strength": {
                "type": "score",
                "score": 3.2,
                "confidence": 0.75,
                "legend": dict(enumerate(pack.questions["hook_strength"].criteria)),
                "probabilities": {"0": 0.0, "1": 0.0, "2": 0.0, "3": 0.8, "4": 0.2},
            },
            "risky_claim": {"type": "noul", "noul": 0.12},
        },
    }
    response = SystemOneResponse.model_validate_json(json.dumps(payload))
    b = from_typesafe("hook_strength", pack.questions["hook_strength"], response)
    assert b.value == 3.2 and b.confidence == 0.75
    assert sorted(b.legend) == ["0", "1", "2", "3", "4"]
    assert b.legend["0"] == pack.questions["hook_strength"].criteria[0]
    assert b.probabilities == {"0": 0.0, "1": 0.0, "2": 0.0, "3": 0.8, "4": 0.2}
    a = from_typesafe("hook_type", pack.questions["hook_type"], response)
    assert a.value == "story" and a.probabilities == {"story": 0.7, "none": 0.3}
    c = from_typesafe("risky_claim", pack.questions["risky_claim"], response)
    assert c.value == 0.12 and c.probabilities is None and c.legend is None


def test_to_typesafe_carries_text_and_order():
    pack = load_pack(RUBRICS / "creator-hooks-v1.yaml")
    q = pack.questions["persona_fit"]
    score = to_typesafe(q)
    assert score.instructions == q.instructions
    assert list(score.criteria) == q.criteria
    noul = to_typesafe(pack.questions["risky_claim"])
    assert noul.model_dump() == {
        "type": "noul",
        "instructions": pack.questions["risky_claim"].instructions,
    }


@pytest.mark.parametrize(
    "name", ["../rubrics/creator-hooks-v1", "/etc/creator-hooks-v1", "a/b", ""]
)
def test_find_pack_rejects_path_like_names(name):
    with pytest.raises(PackNotFound):
        find_pack(name, RUBRICS)


def _write_variant(tmp_path: Path, mutate) -> Path:
    data = yaml.safe_load((RUBRICS / "creator-hooks-v1.yaml").read_text(encoding="utf-8"))
    mutate(data)
    path = tmp_path / "variant.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d["metadata_pass"].append("missing_question"),
        lambda d: d["selection"]["weights"].update({"hook_type": 0.1}),
        lambda d: d["selection"]["weights"].update({"missing_question": 0.1}),
        lambda d: d["selection"]["diversity"].update({"hook_strength": {"max_share": 0.5}}),
        lambda d: d["selection"]["diversity"].update({"missing_question": {"max_share": 0.5}}),
    ],
    ids=[
        "metadata_unknown",
        "weight_on_choice",
        "weight_unknown",
        "diversity_on_score",
        "diversity_unknown",
    ],
)
def test_load_pack_rejects_contract_violations(tmp_path, mutate):
    with pytest.raises(ValueError):
        load_pack(_write_variant(tmp_path, mutate))


def test_with_persona_criteria_does_not_alias_input():
    pack = load_pack(RUBRICS / "creator-hooks-v1.yaml")
    new = with_persona_criteria(pack, ["a", "b", "c", "d", "e"])
    assert isinstance(new.questions["persona_fit"], ScoreQuestion)
    assert new.questions["persona_fit"].instructions == pack.questions["persona_fit"].instructions
    assert new.questions["hook_type"] == pack.questions["hook_type"]
    assert new.questions["hook_type"] is not pack.questions["hook_type"]
    assert new.questions is not pack.questions
    with pytest.raises(ValueError):
        with_persona_criteria(pack, ["a", "b", "c", "d", "e", "f"])
