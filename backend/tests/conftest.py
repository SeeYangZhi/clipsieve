"""Shared fixtures. Later plans rely on these names (overview Addendum A.14)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
import structlog
from sqlalchemy import Engine

from clipsieve.models import Post
from clipsieve.store.db import get_engine, init_db
from clipsieve.store.repo import RunRepository

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _reset_structlog() -> Iterator[None]:
    """Undo configure_logging() and bound context after every test.

    configure_logging() binds the current sys.stderr, which pytest's capsys swaps for a stream
    it closes after the test; without this reset, later tests that log hit a closed file.
    """
    yield
    structlog.reset_defaults()
    structlog.contextvars.clear_contextvars()


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    d = tmp_path / "data"
    d.mkdir()
    return d


@pytest.fixture
def tmp_data_dir(data_dir: Path) -> Path:
    """Alias of `data_dir`; same directory."""
    return data_dir


@pytest.fixture
def engine(data_dir: Path) -> Iterator[Engine]:
    eng = get_engine(data_dir)
    init_db(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def repo(data_dir: Path, engine: Engine) -> RunRepository:
    return RunRepository(data_dir, engine)


@pytest.fixture
def fixture_posts() -> list[Post]:
    """The five posts under tests/fixtures/posts/, sorted by id (local:fx-001 .. local:fx-005)."""
    posts = [
        Post.model_validate_json(f.read_text(encoding="utf-8"))
        for f in (FIXTURES / "posts").glob("*.json")
    ]
    return sorted(posts, key=lambda p: p.id)
