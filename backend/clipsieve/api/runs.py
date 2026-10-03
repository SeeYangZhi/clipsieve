"""Run lifecycle routes: create, list, get, edit plan, approve, pause, resume, posts, report,
reselect. Planning and the pipeline run as background tasks tracked in `ctx.tasks`."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from functools import partial
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_serializer

from clipsieve.api.context import AppContext, context_dependency
from clipsieve.judge.rubric import (
    PASS_ONE,
    PASS_TWO,
    PackNotFound,
    find_pack,
    with_persona_criteria,
)
from clipsieve.logging import get_logger
from clipsieve.models import Brief, JudgeResult, Plan, Post, Report, RubricPack, Run, Stage
from clipsieve.pipeline.runner import post_state
from clipsieve.pipeline.state import load_state
from clipsieve.select.scoring import composite
from clipsieve.select.select import Selection
from clipsieve.store.repo import RunNotFound

log = get_logger(__name__)
router = APIRouter()

Ctx = Annotated[AppContext, Depends(context_dependency)]
DEFAULT_QUANTITY = 500
MAX_ERROR_MESSAGE = 1000
MAX_LATE_PAUSE_RERUNS = 10
FINISHED = (Stage.done, Stage.failed)

PostState = Literal[
    "collected", "dropped_pass_one", "judged", "shortlisted", "review", "judge_failed"
]


class CreateRunBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    brief: str = Field(min_length=1)
    platforms: list[str] = Field(min_length=1)
    quantities: dict[str, Annotated[int, Field(ge=1)]]
    rubric_pack: str = "creator-hooks-v1"
    language_hint: str | None = None


class ReselectBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    weights: dict[str, float]


class PostView(BaseModel):
    post: Post
    judge: dict[str, JudgeResult]
    composite: float | None = None
    state: PostState


class PostsPage(BaseModel):
    items: list[PostView]
    total: int


class RunWithPlan(BaseModel):
    run: Run
    plan: Plan | None

    @model_serializer(mode="wrap")
    def _plan_key_always_present(self, handler):
        """`plan` is `null` until the planner has written one (contract `{run, plan|null}`);
        every other optional field stays absent under `exclude_none`."""
        data = handler(self)
        data.setdefault("plan", None)
        return data


# ---- helpers -------------------------------------------------------------------------------


def get_run_or_404(ctx: AppContext, run_id: str) -> Run:
    try:
        return ctx.repo.get_run(run_id)
    except RunNotFound as exc:
        raise HTTPException(404, f"run {run_id} not found") from exc


def _check_pack(plan: Plan, ctx: AppContext) -> RubricPack:
    try:
        pack = find_pack(plan.rubric_pack, ctx.rubrics_dir)
        return with_persona_criteria(pack, list(plan.persona_fit_criteria))
    except (PackNotFound, ValueError) as exc:
        raise HTTPException(422, f"invalid plan: {exc}") from exc


def _log_task_end(run_id: str, kind: str, task: asyncio.Task[None]) -> None:
    """A background crash must not vanish: log it with its traceback."""
    if task.cancelled():
        log.warning("run_task_cancelled", run_id=run_id, task=kind)
        return
    exc = task.exception()
    if exc is not None:
        log.error("run_task_failed", run_id=run_id, task=kind, error=repr(exc), exc_info=exc)


def _spawn(ctx: AppContext, run_id: str, coro: Coroutine[Any, Any, None], kind: str) -> None:
    task = asyncio.create_task(coro, name=f"{kind}:{run_id}")
    ctx.tasks[run_id] = task
    task.add_done_callback(partial(_log_task_end, run_id, kind))


async def _plan(ctx: AppContext, run_id: str) -> None:
    """Plan in the background. A failure is logged and becomes a recoverable `error` event
    (`where: planner`) so the live view shows it; the user can still PUT a plan by hand."""
    runner = ctx.runner_for(run_id)
    try:
        await runner.plan()
    except Exception as exc:
        log.exception("run_plan_failed", run_id=run_id)
        run = ctx.repo.get_run(run_id)
        run.counters.errors += 1
        ctx.repo.save_run(run)
        payload = {"where": "planner", "message": str(exc)[:MAX_ERROR_MESSAGE], "recoverable": True}
        runner.events.emit("error", Stage.planning, payload)


async def _drive(ctx: AppContext, run_id: str) -> None:
    """`run()` under the run's lock. A pause that lands after a resume can still end `run()`
    paused (Task 9: posts skipped while the flag was set); with no pause outstanding, clear
    `paused` and run again."""
    runner = ctx.runner_for(run_id)
    async with ctx.lock_for(run_id):
        for _ in range(MAX_LATE_PAUSE_RERUNS):
            await runner.run()
            run = ctx.repo.get_run(run_id)
            if not run.paused or run_id in ctx.pause_requests or run.stage in FINISHED:
                return
            log.info("run_late_pause_rerun", run_id=run_id, stage=run.stage.value)
            run.paused = False
            ctx.repo.save_run(run)
        log.warning("run_late_pause_rerun_limit", run_id=run_id)


# ---- routes --------------------------------------------------------------------------------


@router.post("/runs", response_model=Run, status_code=201, response_model_exclude_none=True)
async def create_run(body: CreateRunBody, ctx: Ctx) -> Run:
    unknown = [p for p in body.platforms if p not in ctx.adapters]
    if unknown:
        raise HTTPException(422, f"no adapter for platforms: {', '.join(unknown)}")
    try:
        find_pack(body.rubric_pack, ctx.rubrics_dir)
    except PackNotFound as exc:
        raise HTTPException(422, f"unknown rubric pack: {body.rubric_pack}") from exc
    brief = Brief(
        text=body.brief, topic="", audience="", persona="", language_hint=body.language_hint
    )
    quantities = {p: body.quantities.get(p, DEFAULT_QUANTITY) for p in body.platforms}
    run = ctx.repo.create_run(brief, body.platforms, quantities, body.rubric_pack)
    ctx.runner_for(run.id)  # its constructor emits run_created (Task 9); never emit it here
    _spawn(ctx, run.id, _plan(ctx, run.id), "plan")
    return run


@router.get("/runs", response_model=list[Run], response_model_exclude_none=True)
async def list_runs(ctx: Ctx) -> list[Run]:
    return ctx.repo.list_runs()


@router.get("/runs/{run_id}", response_model=RunWithPlan, response_model_exclude_none=True)
async def get_run(run_id: str, ctx: Ctx) -> RunWithPlan:
    run = get_run_or_404(ctx, run_id)
    return RunWithPlan(run=run, plan=ctx.repo.get_plan(run_id))


@router.put("/runs/{run_id}/plan", response_model=Plan, response_model_exclude_none=True)
async def save_plan(run_id: str, plan: Plan, ctx: Ctx) -> Plan:
    run = get_run_or_404(ctx, run_id)
    if run.stage != Stage.planning:
        raise HTTPException(409, "plan can only be edited before approval")
    if ctx.busy(run_id):
        raise HTTPException(409, "the planner is still writing this plan")
    _check_pack(plan, ctx)
    plan = plan.model_copy(update={"run_id": run_id, "approved_at": None})
    ctx.repo.save_plan(run_id, plan)
    return plan


@router.post("/runs/{run_id}/approve", response_model=Run, response_model_exclude_none=True)
async def approve(run_id: str, ctx: Ctx) -> Run:
    run = get_run_or_404(ctx, run_id)
    if run.stage != Stage.planning:
        raise HTTPException(409, f"run is already {run.stage.value}")
    plan = ctx.repo.get_plan(run_id)
    if plan is None or ctx.busy(run_id):
        raise HTTPException(409, "plan is not ready yet")
    _check_pack(plan, ctx)
    try:
        await ctx.runner_for(run_id).approve(plan)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    _spawn(ctx, run_id, _drive(ctx, run_id), "run")
    return get_run_or_404(ctx, run_id)


@router.post("/runs/{run_id}/pause", response_model=Run, response_model_exclude_none=True)
async def pause(run_id: str, ctx: Ctx) -> Run:
    """Cooperative and sticky: `run.paused` turns true when the pipeline reaches a pause point
    (before approval, as soon as the pipeline starts)."""
    run = get_run_or_404(ctx, run_id)
    ctx.runner_for(run_id).pause()
    ctx.pause_requests.add(run_id)
    return run


@router.post("/runs/{run_id}/resume", response_model=Run, response_model_exclude_none=True)
async def resume(run_id: str, ctx: Ctx) -> Run:
    run = get_run_or_404(ctx, run_id)
    ctx.runner_for(run_id).resume_flag()
    ctx.pause_requests.discard(run_id)
    if run.stage == Stage.planning or run.stage in FINISHED:
        return run
    if ctx.busy(run_id):
        return run  # the running `_drive` re-runs if a late pause still wins
    if run.paused:
        run.paused = False
        ctx.repo.save_run(run)
    _spawn(ctx, run_id, _drive(ctx, run_id), "run")
    return get_run_or_404(ctx, run_id)


@router.get("/runs/{run_id}/posts", response_model=PostsPage, response_model_exclude_none=True)
async def posts(
    run_id: str,
    ctx: Ctx,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> PostsPage:
    get_run_or_404(ctx, run_id)
    state = load_state(ctx.repo.paths(run_id))
    selection = ctx.repo.get_selection(run_id)
    judged_two = {r.post_id for r in ctx.repo.list_judge_results(run_id, PASS_TWO)}
    pack: RubricPack | None = None
    items: list[PostView] = []
    for post in ctx.repo.list_posts(run_id, offset, limit):
        judge: dict[str, JudgeResult] = {}
        for pass_name in (PASS_ONE, PASS_TWO):
            result = ctx.repo.get_judge_result(run_id, post.id, pass_name)
            if result is not None:
                judge[pass_name] = result
        comp: float | None = None
        if selection is not None and post.id in selection.scores:
            comp = selection.scores[post.id]  # reflects the latest reselect weights
        elif PASS_TWO in judge:
            if pack is None:
                plan = ctx.repo.get_plan(run_id)
                pack = _check_pack(plan, ctx) if plan is not None else None
            if pack is not None:
                comp = composite(judge[PASS_TWO], pack)
        items.append(
            PostView(
                post=post,
                judge=judge,
                composite=comp,
                state=post_state(post.id, state, selection, judged_two),
            )
        )
    return PostsPage(items=items, total=ctx.repo.count_posts(run_id))


@router.get("/runs/{run_id}/report", response_model=Report, response_model_exclude_none=True)
async def report(run_id: str, ctx: Ctx) -> Report:
    get_run_or_404(ctx, run_id)
    rep = ctx.repo.get_report(run_id)
    if rep is None:
        raise HTTPException(404, "no report yet")
    return rep


@router.post("/runs/{run_id}/reselect", response_model=Selection, response_model_exclude_none=True)
async def reselect(run_id: str, body: ReselectBody, ctx: Ctx) -> Selection:
    """Re-rank stored pass-two results with other weights. Returns the new `Selection`
    directly: live readers stop at `done`, so they never see the extra `selected` event."""
    get_run_or_404(ctx, run_id)
    if ctx.repo.get_selection(run_id) is None:
        raise HTTPException(409, "nothing selected yet")
    if ctx.busy(run_id):
        raise HTTPException(409, "run is still in progress")
    try:
        return await ctx.runner_for(run_id).reselect(body.weights)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
