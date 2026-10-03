"""Files-first run repository.

Writes JSON files under data/runs/<run_id>/ first, then mirrors them to SQLite.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel
from sqlalchemy import Engine
from sqlmodel import Session, select

from clipsieve.models import Brief, Counters, Evidence, JudgeResult, Plan, Post, Report, Run
from clipsieve.select.select import Selection
from clipsieve.store.db import (
    EvidenceRow,
    JudgeResultRow,
    PlanRow,
    PostRow,
    ReportRow,
    RunRow,
    SelectionRow,
)
from clipsieve.store.paths import RunPaths


class RunNotFound(Exception):
    pass


class PostNotFound(KeyError):
    pass


def _write_json(path: Path, model: BaseModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(model.model_dump_json(indent=2, by_alias=True), encoding="utf-8")
    tmp.replace(path)


def _read_json[M: BaseModel](path: Path, model: type[M]) -> M:
    return model.model_validate_json(path.read_text(encoding="utf-8"))


def _revalidate[M: BaseModel](model: M) -> M:
    """Coerce plain values assigned after construction (run.stage = "collecting") to their types."""
    return type(model).model_validate(dict(model))


def _dump(model: BaseModel) -> str:
    return model.model_dump_json(by_alias=True)


def new_run_id() -> str:
    return "run_" + uuid.uuid4().hex[:12]


class RunRepository:
    def __init__(self, data_dir: Path, engine: Engine) -> None:
        self.data_dir = Path(data_dir)
        self.engine = engine

    def paths(self, run_id: str) -> RunPaths:
        return RunPaths(self.data_dir, run_id)

    # runs

    def create_run(
        self, brief: Brief, platforms: list[str], quantities: dict[str, int], rubric_pack: str
    ) -> Run:
        run = Run(
            id=new_run_id(),
            created_at=datetime.now(UTC),
            stage="planning",
            brief=brief,
            platforms=platforms,
            quantities=quantities,
            rubric_pack=rubric_pack,
            counters=Counters(
                collected=0,
                pass_one_kept=0,
                judged=0,
                shortlisted=0,
                review=0,
                errors=0,
                jev_input_tokens=0,
                jev_cost_usd=0.0,
                elapsed_s=0.0,
            ),
            paused=False,
        )
        self.paths(run.id).ensure()
        self.save_run(run)
        return run

    def save_run(self, run: Run) -> None:
        run = _revalidate(run)
        _write_json(self.paths(run.id).run_json, run)
        with Session(self.engine) as s:
            s.merge(
                RunRow(
                    id=run.id,
                    created_at=run.created_at.isoformat(),
                    stage=run.stage.value,
                    data=_dump(run),
                )
            )
            s.commit()

    def get_run(self, run_id: str) -> Run:
        with Session(self.engine) as s:
            row = s.get(RunRow, run_id)
        if row is None:
            raise RunNotFound(run_id)
        return Run.model_validate_json(row.data)

    def list_runs(self) -> list[Run]:
        with Session(self.engine) as s:
            rows = s.exec(select(RunRow).order_by(RunRow.created_at.desc())).all()
        return [Run.model_validate_json(r.data) for r in rows]

    # plan

    def save_plan(self, run_id: str, plan: Plan) -> None:
        _write_json(self.paths(run_id).plan_json, plan)
        with Session(self.engine) as s:
            s.merge(PlanRow(run_id=run_id, data=_dump(plan)))
            s.commit()

    def get_plan(self, run_id: str) -> Plan | None:
        with Session(self.engine) as s:
            row = s.get(PlanRow, run_id)
        return Plan.model_validate_json(row.data) if row else None

    # posts

    def upsert_post(self, run_id: str, post: Post) -> None:
        _write_json(self.paths(run_id).post_json(post.id), post)
        with Session(self.engine) as s:
            s.merge(
                PostRow(
                    run_id=run_id,
                    post_id=post.id,
                    collected_at=post.collected_at.isoformat(),
                    data=_dump(post),
                )
            )
            s.commit()

    def get_post(self, run_id: str, post_id: str) -> Post:
        with Session(self.engine) as s:
            row = s.get(PostRow, (run_id, post_id))
        if row is None:
            raise PostNotFound(post_id)
        return Post.model_validate_json(row.data)

    def list_posts(self, run_id: str, offset: int = 0, limit: int = 100) -> list[Post]:
        with Session(self.engine) as s:
            rows = s.exec(
                select(PostRow)
                .where(PostRow.run_id == run_id)
                .order_by(PostRow.collected_at, PostRow.post_id)
                .offset(offset)
                .limit(limit)
            ).all()
        return [Post.model_validate_json(r.data) for r in rows]

    def count_posts(self, run_id: str) -> int:
        with Session(self.engine) as s:
            return len(s.exec(select(PostRow.post_id).where(PostRow.run_id == run_id)).all())

    # evidence

    def save_evidence(self, run_id: str, evidence: Evidence) -> None:
        _write_json(self.paths(run_id).evidence_json(evidence.post_id), evidence)
        with Session(self.engine) as s:
            s.merge(EvidenceRow(run_id=run_id, post_id=evidence.post_id, data=_dump(evidence)))
            s.commit()

    def get_evidence(self, run_id: str, post_id: str) -> Evidence | None:
        with Session(self.engine) as s:
            row = s.get(EvidenceRow, (run_id, post_id))
        return Evidence.model_validate_json(row.data) if row else None

    # judge results

    def save_judge_result(self, run_id: str, result: JudgeResult) -> None:
        result = _revalidate(result)
        _write_json(self.paths(run_id).judge_json(result.post_id, result.pass_name.value), result)
        with Session(self.engine) as s:
            s.merge(
                JudgeResultRow(
                    run_id=run_id,
                    post_id=result.post_id,
                    pass_name=result.pass_name.value,
                    data=_dump(result),
                )
            )
            s.commit()

    def get_judge_result(self, run_id: str, post_id: str, pass_name: str) -> JudgeResult | None:
        with Session(self.engine) as s:
            row = s.get(JudgeResultRow, (run_id, post_id, pass_name))
        return JudgeResult.model_validate_json(row.data) if row else None

    def list_judge_results(self, run_id: str, pass_name: str) -> list[JudgeResult]:
        with Session(self.engine) as s:
            rows = s.exec(
                select(JudgeResultRow)
                .where(JudgeResultRow.run_id == run_id, JudgeResultRow.pass_name == pass_name)
                .order_by(JudgeResultRow.post_id)
            ).all()
        return [JudgeResult.model_validate_json(r.data) for r in rows]

    # selection and report

    def save_selection(self, run_id: str, selection: Selection) -> None:
        _write_json(self.paths(run_id).selection_json, selection)
        with Session(self.engine) as s:
            s.merge(SelectionRow(run_id=run_id, data=_dump(selection)))
            s.commit()

    def get_selection(self, run_id: str) -> Selection | None:
        with Session(self.engine) as s:
            row = s.get(SelectionRow, run_id)
        return Selection.model_validate_json(row.data) if row else None

    def save_report(self, run_id: str, report: Report) -> None:
        _write_json(self.paths(run_id).report_json, report)
        with Session(self.engine) as s:
            s.merge(ReportRow(run_id=run_id, data=_dump(report)))
            s.commit()

    def get_report(self, run_id: str) -> Report | None:
        with Session(self.engine) as s:
            row = s.get(ReportRow, run_id)
        return Report.model_validate_json(row.data) if row else None

    # reindex

    def reindex(self, run_id: str) -> None:
        """Rebuild every SQLite row for a run from its files. Files are canonical."""
        p = self.paths(run_id)
        if not p.run_json.exists():
            raise RunNotFound(run_id)
        with Session(self.engine) as s:
            for table in (
                RunRow,
                PlanRow,
                PostRow,
                EvidenceRow,
                JudgeResultRow,
                SelectionRow,
                ReportRow,
            ):
                key = table.id if table is RunRow else table.run_id
                for row in s.exec(select(table).where(key == run_id)).all():
                    s.delete(row)
            s.commit()
        self.save_run(_read_json(p.run_json, Run))
        if p.plan_json.exists():
            self.save_plan(run_id, _read_json(p.plan_json, Plan))
        for f in sorted((p.root / "posts").glob("*.json")):
            self.upsert_post(run_id, _read_json(f, Post))
        for f in sorted((p.root / "evidence").glob("*.json")):
            self.save_evidence(run_id, _read_json(f, Evidence))
        for f in sorted((p.root / "judge").glob("*.json")):
            self.save_judge_result(run_id, _read_json(f, JudgeResult))
        if p.selection_json.exists():
            self.save_selection(run_id, _read_json(p.selection_json, Selection))
        if p.report_json.exists():
            self.save_report(run_id, _read_json(p.report_json, Report))
