"""The conftest fixtures later plans rely on (overview Addendum A.14)."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, inspect

from clipsieve.models import Post
from clipsieve.store.repo import RunRepository


def test_fixture_posts_are_the_five_fixtures_in_id_order(fixture_posts: list[Post]):
    assert len(fixture_posts) == 5
    assert all(isinstance(p, Post) for p in fixture_posts)
    assert [p.id for p in fixture_posts] == [f"local:fx-00{n}" for n in range(1, 6)]


def test_tmp_data_dir_is_data_dir(tmp_data_dir: Path, data_dir: Path):
    assert tmp_data_dir == data_dir
    assert tmp_data_dir.is_dir()


def test_repo_uses_fresh_initialised_db(repo: RunRepository, engine: Engine, data_dir: Path):
    assert repo.data_dir == data_dir
    assert repo.engine is engine
    assert (data_dir / "clipsieve.db").exists()
    assert "runs" in inspect(engine).get_table_names()
    assert repo.list_runs() == []
