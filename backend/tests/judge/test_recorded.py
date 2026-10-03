import importlib.util
import json
from pathlib import Path

import pytest

from clipsieve.judge.recorded import FixtureMissing, RecordedJudge
from clipsieve.judge.rubric import load_pack, questions_for_pass
from clipsieve.models import JudgeResult

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
RUBRICS = Path(__file__).resolve().parents[3] / "rubrics"
PACK = RUBRICS / "creator-hooks-v1.yaml"


async def test_recorded_judge_replays_fixture_and_records_call():
    judge = RecordedJudge(FIXTURES)
    qs = questions_for_pass(load_pack(PACK), "pass_two")
    result = await judge.judge("local:fx-001", "pass_two", {"any": "state"}, qs, "jev-1.13.0")
    assert isinstance(result, JudgeResult)
    assert result.answers["hook_type"].value == "story"
    assert set(result.answers) == set(qs)
    assert judge.calls == [("local:fx-001", "pass_two")]


async def test_all_ten_fixtures_validate_and_cover_every_question():
    judge = RecordedJudge(FIXTURES)
    pack = load_pack(PACK)
    for i in range(1, 6):
        for pass_name in ("pass_one", "pass_two"):
            qs = questions_for_pass(pack, pass_name)
            r = await judge.judge(f"local:fx-00{i}", pass_name, {}, qs, pack.jev_model)
            assert r.pass_name.value == pass_name
            assert r.model == pack.jev_model
            assert set(r.answers) == set(qs)


async def test_missing_fixture_raises():
    judge = RecordedJudge(FIXTURES)
    with pytest.raises(FixtureMissing):
        await judge.judge("local:nope", "pass_one", {}, {}, "jev-1.13.0")


def test_committed_fixtures_equal_generator_output():
    spec = importlib.util.spec_from_file_location(
        "make_fixtures", FIXTURES / "judge" / "make_fixtures.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    expected = mod.build()
    on_disk = {p.name for p in (FIXTURES / "judge").glob("*.json")}
    assert on_disk == set(expected)
    for name, doc in expected.items():
        assert json.loads((FIXTURES / "judge" / name).read_text(encoding="utf-8")) == doc
