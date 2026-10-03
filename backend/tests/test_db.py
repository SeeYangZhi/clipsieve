from pathlib import Path

from sqlalchemy import inspect

from clipsieve.store.db import get_engine, init_db


def test_init_db_creates_tables(data_dir: Path):
    engine = get_engine(data_dir)
    init_db(engine)
    names = set(inspect(engine).get_table_names())
    assert {"runs", "plans", "posts", "evidence", "judge_results", "selections", "reports"} <= names
    assert (data_dir / "clipsieve.db").exists()


def test_init_db_is_idempotent(data_dir: Path):
    engine = get_engine(data_dir)
    init_db(engine)
    init_db(engine)
