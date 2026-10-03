import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from typesafe_sdk import SystemOneResponse

from clipsieve.evidence.packet import build_metadata_state, build_state
from clipsieve.judge.rubric import (
    PackNotFound,
    find_pack,
    from_typesafe,
    load_pack,
    questions_for_pass,
    to_typesafe,
    with_persona_criteria,
)
from clipsieve.models import Brief, ChoiceQuestion, Evidence, NoulQuestion, ScoreQuestion

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
    "text",
    [
        """# Chinese examples appended to creator-hooks-v1 criteria in bilingual language_mode.
hook_type:
  story: "例：「落地第一天，行李丢了」"
  none: "例：开头只有问候或片头"
hook_strength:
  1: "例：开头是「大家好，欢迎回来」"
  5: "例：「你敢信吗？」加上强烈画面对比和明确利益点"
""",
        "name: [unclosed\n",  # not even YAML
        "- just\n- a list\n",
    ],
    ids=["sidecar", "yaml_error", "list"],
)
def test_find_pack_on_a_yaml_that_is_not_a_pack_is_pack_not_found(tmp_path, text):
    (tmp_path / "foo.zh-examples.yaml").write_text(text, encoding="utf-8")
    with pytest.raises(PackNotFound, match="not a rubric pack"):
        find_pack("foo.zh-examples", tmp_path)


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


# --- rubric text names only real Jev state paths (clipsieve.evidence.packet) ---

_BACKTICKED = re.compile(r"`([^`]+)`")
_PATH = re.compile(r"[A-Za-z_]+(\[\d+\])?(\.[A-Za-z_]+(\[\d+\])?)*")
_SEGMENT = re.compile(r"[A-Za-z_]+|\[\d+\]")


def _texts(question) -> list[str]:
    texts = [question.instructions]
    if isinstance(question, ChoiceQuestion):
        texts += list(question.criteria.values())
    elif isinstance(question, ScoreQuestion):
        texts += list(question.criteria)
    return texts


def _resolves(state: dict, path: str) -> bool:
    """Walk `post.caption`, `transcript[0].text`, `ocr` ... through the state dict."""
    if not _PATH.fullmatch(path):
        return False  # not a plain state path
    node = state
    for seg in _SEGMENT.findall(path):
        if seg.startswith("["):
            index = int(seg[1:-1])
            if not isinstance(node, list) or index >= len(node):
                return False
            node = node[index]
        elif isinstance(node, dict) and seg in node:
            node = node[seg]
        else:
            return False
    return True


def test_rubric_paths_exist_in_jev_state(fixtures_dir, fixture_posts):
    """Every backticked path in an instruction or level resolves in the state Jev is sent.

    Pass-one (metadata_pass) questions must resolve in build_metadata_state and build_state;
    the rest in build_state. local:fx-001 has every optional post field plus transcript and OCR.
    """
    pack = load_pack(RUBRICS / "creator-hooks-v1.yaml")
    brief = Brief(
        text="Singaporean moving to Shanghai, vlog style",
        topic="Shanghai expat life",
        audience="Singaporeans in China",
        persona="Singaporean vlogger new to Shanghai",
    )
    post = next(p for p in fixture_posts if p.id == "local:fx-001")
    evidence = Evidence.model_validate_json(
        (fixtures_dir / "evidence" / "local__fx-001.json").read_text(encoding="utf-8")
    )
    metadata_state = build_metadata_state(brief, post)
    full_state, _ = build_state(brief, post, evidence)
    assert full_state["transcript"] and full_state["ocr"]

    missing = []
    for qid, question in pack.questions.items():
        states = {"pass_two": full_state}
        if qid in pack.metadata_pass:
            states["pass_one"] = metadata_state
        for text in _texts(question):
            for path in _BACKTICKED.findall(text):
                missing += [
                    (qid, pass_name, path)
                    for pass_name, state in states.items()
                    if not _resolves(state, path)
                ]
    assert missing == []
