from pathlib import Path

from clipsieve.store.paths import RunPaths, safe_post_filename


def test_safe_post_filename_replaces_colon_and_slashes():
    assert safe_post_filename("youtube:abc123") == "youtube__abc123"
    assert safe_post_filename("local:fx-001") == "local__fx-001"
    assert safe_post_filename("xiaohongshu:a/b\\c") == "xiaohongshu__a_b_c"


def test_run_paths_layout(tmp_path: Path):
    p = RunPaths(tmp_path, "run_abc")
    assert p.root == tmp_path / "runs" / "run_abc"
    assert p.run_json == p.root / "run.json"
    assert p.plan_json == p.root / "plan.json"
    assert p.events_jsonl == p.root / "events.jsonl"
    assert p.report_json == p.root / "report.json"
    assert p.selection_json == p.root / "selection.json"
    assert p.post_json("local:fx-001") == p.root / "posts" / "local__fx-001.json"
    assert p.raw_path("local:fx-001", "json") == p.root / "raw" / "local__fx-001.json"
    assert p.media_dir("local:fx-001") == p.root / "media" / "local__fx-001"
    assert p.evidence_json("local:fx-001") == p.root / "evidence" / "local__fx-001.json"
    assert (
        p.judge_json("local:fx-001", "pass_two") == p.root / "judge" / "local__fx-001.pass_two.json"
    )


def test_ensure_creates_all_dirs(tmp_path: Path):
    p = RunPaths(tmp_path, "run_abc")
    p.ensure()
    for sub in ["posts", "raw", "media", "evidence", "judge"]:
        assert (p.root / sub).is_dir()
