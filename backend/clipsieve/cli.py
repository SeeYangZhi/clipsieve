"""`sieve` command line. The only module in clipsieve/ allowed to print, and only in `_say` and
`_json`; everything else logs through structlog, to stderr.

Exit codes: 0 success, 1 run failed or not found, 2 usage error or declined plan.
Typer commands are sync and drive async work with `asyncio.run`, so no running loop is assumed.
`run` plans in one loop, asks for approval outside any loop (a plain Ctrl-C or EOF at the
prompt), then approves and runs in a second loop; nothing loop-bound outlives the first.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from clipsieve.api.context import AppContext, build_context
from clipsieve.calibration import repo_root, write_results
from clipsieve.config import REPO_ROOT, Settings, get_settings
from clipsieve.events.reader import follow_events, read_events
from clipsieve.judge.recorded import RecordedJudge
from clipsieve.judge.rubric import PackNotFound, find_pack
from clipsieve.judge.typesafe_client import TypeSafeJudge
from clipsieve.logging import configure_logging, get_logger
from clipsieve.models import Brief, Plan, RunEventType, Stage
from clipsieve.pipeline.runner import MAX_ERROR_MESSAGE, Runner
from clipsieve.store.paths import RunPaths
from clipsieve.store.repo import RunNotFound

log = get_logger(__name__)

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="clipsieve: sift social clips, explain the winners.",
)

FINISHED = (Stage.done, Stage.failed)
PROGRESS_POLL_S = 0.1
PROGRESS_DRAIN_S = 5.0

DataDir = Annotated[
    Path | None,
    typer.Option(
        "--data-dir",
        help="Overrides CLIPSIEVE_DATA_DIR. Relative paths resolve against the repo root.",
    ),
]


def _say(msg: str, *, err: bool = False) -> None:
    print(msg, file=sys.stderr if err else sys.stdout, flush=True)  # noqa: T201


def _json(obj: object) -> None:
    print(json.dumps(obj, ensure_ascii=False), flush=True)  # noqa: T201


def _settings(data_dir: Path | None) -> Settings:
    """`get_settings()`, with `--data-dir` in place of `clipsieve_data_dir` when given (A.11)."""
    settings = get_settings()
    if data_dir is None:
        return settings
    resolved = data_dir if data_dir.is_absolute() else REPO_ROOT / data_dir
    return settings.model_copy(update={"clipsieve_data_dir": resolved})


@contextmanager
def _context(data_dir: Path | None) -> Iterator[AppContext]:
    ctx = build_context(_settings(data_dir))
    try:
        yield ctx
    finally:
        ctx.repo.engine.dispose()


def _parse_weights(spec: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for part in filter(None, (p.strip() for p in spec.split(","))):
        key, _, value = (s.strip() for s in part.partition("="))
        try:
            if not key:
                raise ValueError(part)
            out[key] = float(value)
        except ValueError:
            raise typer.BadParameter(
                f"weights must be question=number pairs, got {part!r}", param_hint="--weights"
            ) from None
    if not out:
        raise typer.BadParameter("give at least one question=number pair", param_hint="--weights")
    return out


@app.callback()
def main(
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Log at INFO instead of WARNING (stderr).")
    ] = False,
) -> None:
    configure_logging("INFO" if verbose else "WARNING")


# ---- run ------------------------------------------------------------------------------------


async def _progress(paths: RunPaths, after: int) -> None:
    """Print stage changes and errors as the run appends them; ends at the first terminal event."""
    async for event in follow_events(paths, after=after, poll_s=PROGRESS_POLL_S):
        if event.type == RunEventType.stage_changed:
            _say(f"progress: {event.payload['from']} -> {event.payload['to']}")
        elif event.type == RunEventType.error:
            where = event.payload.get("where", "?")
            post = f" ({event.payload['post_id']})" if "post_id" in event.payload else ""
            _say(f"error: {where}{post}: {event.payload.get('message', '')}", err=True)


async def _plan(runner: Runner) -> Plan | None:
    """`runner.plan()`. A failure is recorded as `api.runs._plan` records it: logged, counted,
    and a recoverable `error` event (`where: planner`); the run stays in planning."""
    try:
        return await runner.plan()
    except Exception as exc:
        log.exception("cli_plan_failed", run_id=runner.run_id)
        run = runner.repo.get_run(runner.run_id)
        run.counters.errors += 1
        runner.repo.save_run(run)
        payload = {"where": "planner", "message": str(exc)[:MAX_ERROR_MESSAGE], "recoverable": True}
        runner.events.emit("error", Stage.planning, payload)
        _say(f"planning failed: {exc}. The run stays in planning.", err=True)
        return None


def _approved(auto_approve: bool) -> int:
    """0 to go ahead, 2 when the plan is declined or nobody can answer the prompt."""
    if auto_approve:
        return 0
    try:
        if typer.confirm("Approve this plan and start the run?", default=False):
            return 0
    except typer.Abort:  # EOF on stdin (non-interactive) or Ctrl-C at the prompt
        _say("", err=True)
        _say(
            "no answer on stdin; pass --auto-approve to run without confirmation. "
            "Run left in planning.",
            err=True,
        )
        return 2
    _say("plan not approved; run left in planning. Approve it later from the dashboard.")
    return 2


async def _approve_and_run(runner: Runner, plan: Plan) -> int:
    """Approve, then run to the end while printing progress from the event log."""
    follower = asyncio.create_task(_progress(runner.paths, after=runner.events.last_seq))
    try:
        await runner.approve(plan)
        await runner.run()
    except Exception as exc:
        log.exception("cli_run_crashed", run_id=runner.run_id)
        _say(f"run stopped: {exc}", err=True)
        return 1
    finally:
        if runner.repo.get_run(runner.run_id).stage in FINISHED:
            # The terminal event is already in the log; let the follower print up to it.
            await asyncio.wait({follower}, timeout=PROGRESS_DRAIN_S)
        follower.cancel()
        await asyncio.gather(follower, return_exceptions=True)
    return 0


@app.command()
def run(
    brief: Annotated[str, typer.Option("--brief", help="Research brief, one or two sentences.")],
    platforms: Annotated[
        str, typer.Option("--platforms", help="Comma-separated platform ids.")
    ] = "youtube",
    limit: Annotated[int, typer.Option("--limit", min=1, help="Posts per platform.")] = 500,
    pack: Annotated[str, typer.Option("--pack", help="Rubric pack name.")] = "creator-hooks-v1",
    auto_approve: Annotated[
        bool, typer.Option("--auto-approve", help="Skip the plan confirmation.")
    ] = False,
    language_hint: Annotated[str | None, typer.Option("--language-hint")] = None,
    data_dir: DataDir = None,
) -> None:
    """Create a run, plan it, confirm the plan, then run it to the end."""
    if not brief.strip():
        raise typer.BadParameter("the brief is empty", param_hint="--brief")
    plats = list(dict.fromkeys(p.strip() for p in platforms.split(",") if p.strip()))
    if not plats:
        raise typer.BadParameter("name at least one platform", param_hint="--platforms")
    with _context(data_dir) as ctx:
        missing = [p for p in plats if p not in ctx.adapters]
        if missing:
            _say(f"no adapter for: {', '.join(missing)}", err=True)
            raise typer.Exit(2)
        try:
            find_pack(pack, ctx.rubrics_dir)
        except PackNotFound as exc:
            _say(f"unknown rubric pack: {pack} ({exc})", err=True)
            raise typer.Exit(2) from None
        brief_model = Brief(
            text=brief, topic="", audience="", persona="", language_hint=language_hint
        )
        run_obj = ctx.repo.create_run(brief_model, plats, {p: limit for p in plats}, pack)
        runner = ctx.runner_for(run_obj.id)  # its constructor emits run_created; never emit here
        _say(f"run_id: {run_obj.id}")

        plan = asyncio.run(_plan(runner))
        if plan is None:
            raise typer.Exit(1)
        _say("plan:")
        _json(plan.model_dump(mode="json", by_alias=True, exclude_none=True))
        code = _approved(auto_approve)
        if code == 0:
            code = asyncio.run(_approve_and_run(runner, plan))
        if code:
            raise typer.Exit(code)

        final = ctx.repo.get_run(run_obj.id)
        _say(f"stage: {final.stage.value}")
        for key, value in final.counters.model_dump().items():
            _say(f"{key}: {value}")
        if final.stage == Stage.failed:
            _say(f"error: {final.error}", err=True)
            raise typer.Exit(1)
        if final.stage != Stage.done:
            _say(f"run stopped at {final.stage.value}", err=True)
            raise typer.Exit(1)


# ---- replay, reselect, reindex --------------------------------------------------------------


@app.command()
def replay(
    run_id: str,
    speed: Annotated[
        float,
        typer.Option("--speed", min=0.0, help="Delay divisor; 2 is twice as fast, 0 no delay."),
    ] = 1.0,
    data_dir: DataDir = None,
) -> None:
    """Print a run's events as JSON lines, at the original pace divided by --speed."""
    paths = RunPaths(_settings(data_dir).clipsieve_data_dir, run_id)
    if not paths.events_jsonl.exists():
        _say(f"run {run_id} not found", err=True)
        raise typer.Exit(1)
    prev = None
    for event in read_events(paths):
        if prev is not None and speed > 0:
            delay = (event.ts - prev).total_seconds() / speed
            if delay > 0:
                time.sleep(delay)
        prev = event.ts
        _json(event.model_dump(mode="json", by_alias=True, exclude_none=True))


@app.command()
def reselect(
    run_id: str,
    weights: Annotated[
        str, typer.Option("--weights", help="e.g. hook_strength=0.5,persona_fit=0.5")
    ],
    data_dir: DataDir = None,
) -> None:
    """Re-rank a finished run's pass-two results with other weights. No Jev calls."""
    parsed = _parse_weights(weights)
    with _context(data_dir) as ctx:
        try:
            ctx.repo.get_run(run_id)
        except RunNotFound:
            _say(f"run {run_id} not found", err=True)
            raise typer.Exit(1) from None
        try:
            selection = asyncio.run(ctx.runner_for(run_id).reselect(parsed))
        except RuntimeError as exc:  # no selection yet
            _say(str(exc), err=True)
            raise typer.Exit(1) from None
    _json(selection.model_dump(mode="json"))


@app.command()
def reindex(run_id: str, data_dir: DataDir = None) -> None:
    """Rebuild a run's SQLite rows from its files."""
    with _context(data_dir) as ctx:
        try:
            ctx.repo.reindex(run_id)
        except RunNotFound:
            _say(f"run {run_id} not found", err=True)
            raise typer.Exit(1) from None
    _say(f"reindexed {run_id}")


# ---- eval -----------------------------------------------------------------------------------

EVAL_MODES = ("raw", "translate", "bilingual")


@app.command("eval")
def eval_cmd(
    pack: Annotated[str, typer.Option("--pack", help="Rubric pack name, e.g. creator-hooks-v1")],
    golden: Annotated[
        Path, typer.Option("--golden", exists=True, dir_okay=False, help="Golden JSONL file")
    ],
    mode: Annotated[str, typer.Option("--mode", help="raw | translate | bilingual")] = "raw",
    rubrics_dir: Annotated[
        Path | None, typer.Option("--rubrics-dir", help="Defaults to <repo>/rubrics")
    ] = None,
    judge_fixtures: Annotated[
        Path | None,
        typer.Option(
            "--judge-fixtures",
            help="Use RecordedJudge on this fixtures dir (reads <dir>/judge/) instead of TypeSafe",
        ),
    ] = None,
) -> None:
    """Score a rubric pack against a golden set and write rubrics/<pack>.calibration.md."""
    if mode not in EVAL_MODES:
        _say(f"--mode must be one of {', '.join(EVAL_MODES)}, got {mode!r}", err=True)
        raise typer.Exit(2)
    if mode == "translate" and judge_fixtures is not None:
        # Recorded answers ignore the state, so translating it would only spend `claude` money.
        _say("--mode translate needs the real judge; drop --judge-fixtures", err=True)
        raise typer.Exit(2)
    root = repo_root()
    rubrics = rubrics_dir or root / "rubrics"
    try:
        rp = find_pack(pack, rubrics)
    except PackNotFound as exc:
        _say(f"unknown rubric pack: {pack} ({exc})", err=True)
        raise typer.Exit(2) from None
    settings = get_settings()
    if judge_fixtures is None and not settings.typesafe_api_key:
        _say("TYPESAFE_API_KEY is not set; set it in .env or pass --judge-fixtures", err=True)
        raise typer.Exit(2)
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from evals.score import ClaudeCliTranslator, IdentityTranslator, render_markdown, score_pack

    judge = (
        RecordedJudge(judge_fixtures)
        if judge_fixtures is not None
        else TypeSafeJudge(settings.typesafe_api_key)
    )
    translator = (
        ClaudeCliTranslator(settings.clipsieve_claude_bin)
        if mode == "translate"
        else IdentityTranslator()
    )

    async def _run():
        try:
            return await score_pack(
                rp, golden, judge, mode=mode, translator=translator, rubrics_dir=rubrics
            )
        finally:
            aclose = getattr(judge, "aclose", None)  # TypeSafeJudge has one, RecordedJudge not
            if aclose is not None:
                await aclose()

    try:
        report = asyncio.run(_run())
    except (OSError, ValueError, RuntimeError) as exc:
        # Missing fixture or `claude` binary (OSError), a bad golden line or unparsable `claude`
        # output (ValueError, which covers JSONDecodeError), a translation failure (RuntimeError).
        log.warning("cli_eval_failed", pack=pack, mode=mode, golden=str(golden), error=str(exc))
        _say(f"eval failed: {exc}", err=True)
        raise typer.Exit(1) from None
    table = render_markdown(report)
    _say(table)
    cal = rubrics / f"{pack}.calibration.md"
    write_results(cal, golden.stem, mode, table, datetime.now(tz=UTC))
    _say(f"wrote {cal}")
