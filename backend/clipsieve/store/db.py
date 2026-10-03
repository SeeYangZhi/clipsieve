"""SQLite index tables. Each row stores canonical JSON in `data`; key columns aid lookup."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine
from sqlmodel import Field, SQLModel, create_engine


class RunRow(SQLModel, table=True):
    __tablename__ = "runs"
    id: str = Field(primary_key=True)
    created_at: str = Field(index=True)
    stage: str
    data: str


class PlanRow(SQLModel, table=True):
    __tablename__ = "plans"
    run_id: str = Field(primary_key=True)
    data: str


class PostRow(SQLModel, table=True):
    __tablename__ = "posts"
    run_id: str = Field(primary_key=True)
    post_id: str = Field(primary_key=True)
    collected_at: str = Field(index=True)
    data: str


class EvidenceRow(SQLModel, table=True):
    __tablename__ = "evidence"
    run_id: str = Field(primary_key=True)
    post_id: str = Field(primary_key=True)
    data: str


class JudgeResultRow(SQLModel, table=True):
    __tablename__ = "judge_results"
    run_id: str = Field(primary_key=True)
    post_id: str = Field(primary_key=True)
    pass_name: str = Field(primary_key=True)
    data: str


class SelectionRow(SQLModel, table=True):
    __tablename__ = "selections"
    run_id: str = Field(primary_key=True)
    data: str


class ReportRow(SQLModel, table=True):
    __tablename__ = "reports"
    run_id: str = Field(primary_key=True)
    data: str


def get_engine(data_dir: Path) -> Engine:
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    return create_engine(
        f"sqlite:///{data_dir / 'clipsieve.db'}", connect_args={"check_same_thread": False}
    )


def init_db(engine: Engine) -> None:
    SQLModel.metadata.create_all(engine)
