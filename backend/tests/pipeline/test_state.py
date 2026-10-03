import pytest
from pydantic import ValidationError

from clipsieve.pipeline.state import RunState, load_state, save_state
from clipsieve.store.paths import RunPaths


def test_missing_state_is_empty(tmp_path):
    assert load_state(RunPaths(tmp_path, "run_x")) == RunState()


def test_state_round_trips_through_state_json(tmp_path):
    paths = RunPaths(tmp_path, "run_x")
    paths.ensure()
    state = RunState(
        pass_one_kept=["a"], pass_one_dropped=["b"], judge_failed=["c"], extracted=["a"]
    )
    save_state(paths, state)
    assert (paths.root / "state.json").is_file()
    assert not (paths.root / "state.json.tmp").exists()
    assert load_state(paths) == state


def test_state_rejects_unknown_keys():
    with pytest.raises(ValidationError):
        RunState.model_validate({"kept": []})
