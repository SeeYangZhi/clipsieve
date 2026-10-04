"""Drives one run through its stages and appends a RunEvent for every step.

Idempotent per post, so `run()` again after a crash or a pause skips finished work: a post whose
judge result row for the pass is in SQLite (`repo.get_judge_result`) is not judged again, and a
post is extracted at most once (`RunState.extracted`). Per-post decisions live in
`<run>/state.json`; see `pipeline/state.py`.
"""

from __future__ import annotations

import asyncio
import shutil
from collections.abc import Coroutine, Iterable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from clipsieve.adapters.base import COVER_NAME, Adapter, cover_fetcher
from clipsieve.config import Settings
from clipsieve.events.writer import EventWriter
from clipsieve.evidence.asr import ASR
from clipsieve.evidence.extract import extract_evidence
from clipsieve.evidence.frames import FrameExtractor
from clipsieve.evidence.ocr import OCR
from clipsieve.evidence.packet import build_metadata_state, build_state, estimate_tokens
from clipsieve.explain.base import (
    ExplainBackend,
    ExplainError,
    ExplainPacket,
    ExplainPost,
    cli_payload,
    validate_report_citations,
)
from clipsieve.judge.base import Judge, JudgeFailed, cost_usd
from clipsieve.judge.rubric import (
    PASS_ONE,
    PASS_TWO,
    find_pack,
    questions_for_pass,
    with_persona_criteria,
)
from clipsieve.logging import get_logger
from clipsieve.models import (
    Brief,
    CommentSummary,
    Evidence,
    JudgeResult,
    OcrItem,
    Plan,
    Post,
    Query,
    RubricPack,
    Run,
    Stage,
    TranscriptSegment,
)
from clipsieve.pipeline.state import RunState, load_state, save_state
from clipsieve.planner.plan import build_plan
from clipsieve.select.scoring import composite
from clipsieve.select.select import Selection, pass_one_keep, select
from clipsieve.store.repo import RunRepository

log = get_logger(__name__)

STAGE_ORDER: list[str] = [
    "planning",
    "collecting",
    "pass_one",
    "extracting",
    "pass_two",
    "selecting",
    "explaining",
    "done",
]
EXTRACT_CONCURRENCY = 2  # ASR and OCR are CPU-bound; backends are shared and lock internally
JUDGE_CONCURRENCY = 16  # the Runner's own gate, so a pause stops new Jev requests promptly
ADAPTER_ERROR_ABORT_RATIO = 0.20
ADAPTER_ERROR_MIN_SEEN = 10
ALL_POSTS = 1_000_000
MAX_ERROR_MESSAGE = 1000
EXPLAIN_TEXT_CAP = 4000  # characters of transcript, and of OCR text, per post in the packet
TRUNCATION_MARKER = "…"

_SKIPPED = object()  # a per-post task that did not start because the run is pausing


class RunPaused(Exception):
    """Raised at a pause point inside `run()`, which catches it and returns normally."""


def post_state(
    post_id: str, state: RunState, selection: Selection | None, judged_pass_two: set[str]
) -> str:
    """One of `collected | dropped_pass_one | judged | shortlisted | review | judge_failed`."""
    if post_id in state.judge_failed:
        return "judge_failed"
    if post_id in state.pass_one_dropped:
        return "dropped_pass_one"
    if selection is not None:
        if post_id in selection.shortlist:
            return "shortlisted"
        if post_id in selection.review:
            return "review"
    if post_id in judged_pass_two:
        return "judged"
    return "collected"


def _empty_evidence(post: Post) -> Evidence:
    return Evidence(
        post_id=post.id,
        transcript=[],
        ocr=[],
        keyframes=[],
        comment_summary=CommentSummary(count=len(post.comments), top_terms=[], sample=[]),
        token_estimate=0,
        truncated=False,
    )


def _cap_text[T: (TranscriptSegment, OcrItem)](items: list[T], cap: int) -> tuple[list[T], bool]:
    """Keep items in order while their joined text fits in `cap` characters. The item that
    crosses the cap is cut there and ends with `TRUNCATION_MARKER`; later items are dropped."""
    out: list[T] = []
    left = cap
    for item in items:
        if len(item.text) <= left:
            out.append(item)
            left -= len(item.text)
            continue
        out.append(item.model_copy(update={"text": item.text[:left] + TRUNCATION_MARKER}))
        return out, True
    return out, False


def _explain_evidence(evidence: Evidence) -> Evidence:
    """A copy with transcript and OCR text capped at `EXPLAIN_TEXT_CAP` characters each, marked
    `truncated` when anything was cut. The stored evidence is never touched."""
    transcript, cut_transcript = _cap_text(evidence.transcript, EXPLAIN_TEXT_CAP)
    ocr, cut_ocr = _cap_text(evidence.ocr, EXPLAIN_TEXT_CAP)
    if not (cut_transcript or cut_ocr):
        return evidence
    return evidence.model_copy(update={"transcript": transcript, "ocr": ocr, "truncated": True})


def build_explain_packet(
    run_id: str,
    brief: Brief,
    posts: list[Post],
    evidence: dict[str, Evidence],
    judge: dict[str, JudgeResult],
    aggregates: dict[str, dict[str, int]],
) -> ExplainPacket:
    """The explain input for a shortlist. Posts go in without their raw comments (the evidence
    `comment_summary` keeps a sample) and each post's transcript and OCR text is capped, so the
    packet stays a bounded size however long the videos or comment threads are."""
    trimmed = {pid: _explain_evidence(ev) for pid, ev in evidence.items()}
    packet = ExplainPacket(
        brief=brief,
        posts=[ExplainPost.model_validate(p) for p in posts],
        evidence=trimmed,
        judge=judge,
        aggregates=aggregates,
        keyframes={pid: list(ev.keyframes) for pid, ev in trimmed.items()},
    )
    text = cli_payload("explain", packet)  # what the claude_cli backend sends
    log.info(
        "explain_packet_built",
        run_id=run_id,
        posts=len(packet.posts),
        approx_chars=len(text),
        approx_tokens=estimate_tokens(text),
    )
    return packet


class Runner:
    """One Runner per run; one `run()` at a time. Construct it after `repo.create_run`."""

    def __init__(
        self,
        run_id: str,
        settings: Settings,
        repo: RunRepository,
        adapters: dict[str, Adapter],
        judge: Judge,
        explain: ExplainBackend,
        asr: ASR,
        ocr: OCR,
        frames: FrameExtractor,
        rubrics_dir: Path,
    ) -> None:
        self.run_id = run_id
        self.settings = settings
        self.repo = repo
        self.adapters = adapters
        self.judge = judge
        self.explain_backend = explain
        self.asr, self.ocr, self.frames = asr, ocr, frames  # one shared instance each (B.13)
        self.rubrics_dir = Path(rubrics_dir)
        self.paths = repo.paths(run_id)
        self.paths.ensure()
        self.events = EventWriter(self.paths, run_id)
        self._pause = False
        self._halt = False
        if self.events.last_seq == 0:
            run = self._run()
            self.events.emit(
                "run_created",
                run.stage,
                {
                    "brief": run.brief.model_dump(mode="json"),
                    "platforms": list(run.platforms),
                    "quantities": dict(run.quantities),
                },
            )

    # ---- control ------------------------------------------------------------------------

    def pause(self) -> None:
        """Cooperative: in-flight posts finish, no new post or stage starts."""
        self._pause = True

    def resume_flag(self) -> None:
        """Clear the pause flag. The caller also clears `run.paused`, then calls `run()`."""
        self._pause = False

    @property
    def _stopping(self) -> bool:
        return self._pause or self._halt

    def _check_pause(self) -> None:
        if self._pause:
            raise RunPaused()

    async def _settle(self, coros: Iterable[Coroutine[Any, Any, Any]]) -> list[Any]:
        """Await every per-post task. After the first failure, tasks not yet started skip
        (`_halt`) and in-flight ones finish and record their work; then the failure is raised."""

        async def guarded(coro: Coroutine[Any, Any, Any]) -> Any:
            try:
                return await coro
            except BaseException:
                self._halt = True
                raise

        try:
            results = await asyncio.gather(*(guarded(c) for c in coros), return_exceptions=True)
        finally:
            self._halt = False
        for r in results:
            if isinstance(r, BaseException):
                raise r
        if any(r is _SKIPPED for r in results):
            raise RunPaused()
        return results

    # ---- helpers ------------------------------------------------------------------------

    def _run(self) -> Run:
        return self.repo.get_run(self.run_id)

    def _save_counters(self, run: Run) -> None:
        elapsed = (datetime.now(UTC) - run.created_at).total_seconds()
        run.counters.elapsed_s = round(max(0.0, elapsed), 1)
        self.repo.save_run(run)

    def _set_stage(self, run: Run, to: str) -> Run:
        frm = run.stage.value
        if frm != to:
            run.stage = Stage(to)  # always an enum member; validate_assignment is off
            self.repo.save_run(run)
            self.events.emit("stage_changed", to, {"from": frm, "to": to})
            log.info("run_stage", run_id=self.run_id, stage=to)
        return run

    def _error(
        self,
        run: Run,
        where: str,
        message: str,
        post_id: str | None = None,
        recoverable: bool = True,
    ) -> None:
        run.counters.errors += 1
        self._save_counters(run)
        payload: dict[str, Any] = {
            "where": where,
            "message": message[:MAX_ERROR_MESSAGE],
            "recoverable": recoverable,
        }
        if post_id is not None:
            payload["post_id"] = post_id
        self.events.emit("error", run.stage, payload)
        log.warning("run_error", run_id=self.run_id, where=where, post_id=post_id)

    def _plan(self) -> Plan:
        plan = self.repo.get_plan(self.run_id)
        if plan is None or plan.approved_at is None:
            raise RuntimeError(f"run {self.run_id} has no approved plan")
        return plan

    def _pack(self, plan: Plan) -> RubricPack:
        pack = find_pack(plan.rubric_pack, self.rubrics_dir)
        return with_persona_criteria(pack, list(plan.persona_fit_criteria))

    def _reconcile_counters(self, run: Run) -> None:
        """Recount from the stored posts and judge rows and `state.json`, so a crash between a
        write and a counter save leaves no drift on resume. `errors`, `shortlisted` and `review`
        are kept as saved."""
        rstate = load_state(self.paths)
        p1 = self.repo.list_judge_results(self.run_id, PASS_ONE)
        p2 = self.repo.list_judge_results(self.run_id, PASS_TWO)
        tokens = sum(r.input_tokens for r in p1 + p2)
        counters = run.counters
        counters.collected = self.repo.count_posts(self.run_id)
        counters.pass_one_kept = len(rstate.pass_one_kept)
        counters.judged = sum(1 for r in p2 if r.post_id not in rstate.judge_failed)
        counters.jev_input_tokens = tokens
        counters.jev_cost_usd = round(cost_usd(tokens), 6)
        self._save_counters(run)

    # ---- planning -----------------------------------------------------------------------

    async def plan(self) -> Plan:
        run = self._run()
        if run.stage != Stage.planning:
            raise RuntimeError(f"run {self.run_id} is past planning ({run.stage.value})")
        plan = await asyncio.to_thread(
            build_plan,
            self.run_id,
            run.brief.text,
            list(run.platforms),
            dict(run.quantities),
            run.rubric_pack,
            run.brief.language_hint,
            self.explain_backend,
            self.rubrics_dir,
        )
        self.repo.save_plan(self.run_id, plan)
        self.events.emit("plan_ready", Stage.planning, {"plan": plan.model_dump(mode="json")})
        return plan

    async def approve(self, plan: Plan) -> None:
        run = self._run()
        if run.stage != Stage.planning:
            raise RuntimeError(f"run {self.run_id} is already approved ({run.stage.value})")
        plan = plan.model_copy(update={"run_id": self.run_id, "approved_at": datetime.now(UTC)})
        self._pack(plan)  # an unknown pack or bad persona criteria fail before anything is saved
        self.repo.save_plan(self.run_id, plan)
        run.brief = plan.brief
        run.rubric_pack = plan.rubric_pack
        run.quantities = {**run.quantities, **plan.quantities}
        self.repo.save_run(run)
        self.events.emit("plan_approved", Stage.planning, {"plan": plan.model_dump(mode="json")})
        self._set_stage(run, "collecting")

    # ---- main loop ----------------------------------------------------------------------

    async def run(self) -> None:
        """Run from the current stage to `done`. Returns normally when paused (sets
        `run.paused`) or when explaining fails (stage `failed`); other errors propagate and
        leave the stage where it was, ready for `run()` again."""
        run = self._run()
        if run.stage in (Stage.done, Stage.failed):
            return
        if run.stage == Stage.planning:
            raise RuntimeError("plan must be approved before run()")
        self._reconcile_counters(run)
        stages = {
            "collecting": self._collect,
            "pass_one": self._pass_one,
            "extracting": self._extract,
            "pass_two": self._pass_two,
            "selecting": self._select,
            "explaining": self._explain,
        }
        try:
            for stage in STAGE_ORDER[STAGE_ORDER.index(run.stage.value) : -1]:
                run = self._set_stage(self._run(), stage)
                self._check_pause()
                await stages[stage](run)
            run = self._set_stage(self._run(), "done")
            self._save_counters(run)
            self.events.emit("done", Stage.done, {"counters": run.counters.model_dump(mode="json")})
            log.info("run_done", run_id=self.run_id)
        except RunPaused:
            run = self._run()
            run.paused = True
            self._save_counters(run)
            log.info("run_paused", run_id=self.run_id, stage=run.stage.value)
        except ExplainError as exc:
            self._fail(str(exc))

    def _fail(self, message: str) -> None:
        run = self._run()
        # E.8 as amended: the error goes first, while the stage is still `explaining`. Readers
        # (follow_events, the frontend) stop at the first failed-stage event, so stage_changed
        # to `failed` must be the last line in the log.
        self._error(run, "explain", message, recoverable=False)
        frm = run.stage.value
        run.error = message
        run.stage = Stage.failed
        self.repo.save_run(run)
        self.events.emit("stage_changed", Stage.failed, {"from": frm, "to": "failed"})
        log.warning("run_failed", run_id=self.run_id, stage=frm)

    # ---- collecting ---------------------------------------------------------------------

    async def _collect(self, run: Run) -> None:
        plan = self._plan()
        existing = {p.id for p in self.repo.list_posts(self.run_id, 0, ALL_POSTS)}
        for platform in run.platforms:
            where = f"adapter.{platform}"
            adapter = self.adapters.get(platform)
            if adapter is None:
                self._error(run, where, f"no adapter registered for {platform}")
                continue
            try:
                health = await asyncio.to_thread(adapter.healthcheck)
            except Exception as exc:
                self._error(run, where, f"{platform} healthcheck failed: {exc!r}")
                continue
            if not health.ok:
                self._error(run, where, f"{platform} adapter unhealthy: {health.message}")
                continue
            queries = [q for q in plan.queries if q.platform == platform]
            limit = run.quantities.get(platform, 0)
            await self._collect_platform(run, platform, adapter, queries, limit, existing)

    async def _collect_platform(
        self,
        run: Run,
        platform: str,
        adapter: Adapter,
        queries: list[Query],
        limit: int,
        existing: set[str],
    ) -> None:
        """Pull posts one at a time so each is live as soon as the adapter yields it."""
        where = f"adapter.{platform}"
        seen = errors = 0
        it: Iterator[Post] | None = None
        try:
            it = iter(await asyncio.to_thread(adapter.search, queries, limit))
            while True:
                self._check_pause()
                post = await asyncio.to_thread(next, it, None)
                if post is None:
                    break
                seen += 1
                if post.id in existing:
                    continue  # stored before a pause or crash; the search yields it again
                try:
                    post = self._relocate_raw(post)
                    self.repo.upsert_post(self.run_id, post)
                except Exception as exc:
                    errors += 1
                    self._error(run, where, f"could not store post: {exc!r}", post_id=post.id)
                else:
                    existing.add(post.id)
                    run.counters.collected += 1
                    self._save_counters(run)
                    self.events.emit(
                        "post_collected", Stage.collecting, {"post": post.model_dump(mode="json")}
                    )
                    await self._fetch_cover(adapter, post)
                if seen >= ADAPTER_ERROR_MIN_SEEN and errors / seen > ADAPTER_ERROR_ABORT_RATIO:
                    self._error(run, where, f"{platform} aborted: {errors}/{seen} posts failed")
                    break
        except RunPaused:
            raise
        except Exception as exc:
            self._error(run, where, f"{platform} search failed: {exc!r}")
        finally:
            close = getattr(it, "close", None)
            if close is not None:
                close()

    async def _fetch_cover(self, adapter: Adapter, post: Post) -> None:
        """Optional adapter cover into `media_dir/thumb.jpg` (B.15), one small GET inline per
        post. Never an `error` event: a failure only costs the tile its image."""
        fetch = cover_fetcher(adapter)
        if fetch is None:
            return
        dest = self.paths.media_dir(post.id)
        if (dest / COVER_NAME).exists():
            return
        try:
            await asyncio.to_thread(fetch, post, dest)
        except Exception as exc:  # noqa: BLE001 - a cover must never fail the post
            log.warning("cover_failed", post_id=post.id, error=repr(exc))

    def _relocate_raw(self, post: Post) -> Post:
        """Move the adapter's incoming raw payload into the run (B.1/B.10). Runs at collection,
        so before any `fetch_media`; `raw_ref` becomes the run-relative `raw/<safe_id>.json`."""
        src = Path(post.raw_ref)
        if not src.is_file():
            raise FileNotFoundError(f"raw payload missing for {post.id}: {post.raw_ref}")
        dst = self.paths.raw_path(post.id, "json")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(src, dst)
        return post.model_copy(update={"raw_ref": dst.relative_to(self.paths.root).as_posix()})

    # ---- judging ------------------------------------------------------------------------

    async def _judge_one(
        self,
        run: Run,
        post_id: str,
        pass_name: str,
        state: dict[str, Any],
        pack: RubricPack,
        rstate: RunState,
    ) -> JudgeResult | None:
        """One Jev request with every question of the pass. None when the post failed."""
        if post_id in rstate.judge_failed:
            return None
        existing = self.repo.get_judge_result(self.run_id, post_id, pass_name)
        if existing is not None:
            return existing
        try:
            result = await self.judge.judge(
                post_id, pass_name, state, questions_for_pass(pack, pass_name), pack.jev_model
            )
        except JudgeFailed as exc:
            if post_id not in rstate.judge_failed:
                rstate.judge_failed.append(post_id)
                save_state(self.paths, rstate)
            self._error(run, f"judge.{pass_name}", str(exc), post_id=post_id)
            return None
        self.repo.save_judge_result(self.run_id, result)
        run.counters.jev_input_tokens += result.input_tokens
        run.counters.jev_cost_usd = round(cost_usd(run.counters.jev_input_tokens), 6)
        return result

    async def _pass_one(self, run: Run) -> None:
        rstate = load_state(self.paths)
        if rstate.pass_one_kept or rstate.pass_one_dropped:
            return  # decided before a pause or crash
        plan = self._plan()
        pack = self._pack(plan)
        posts = self.repo.list_posts(self.run_id, 0, ALL_POSTS)
        gate = asyncio.Semaphore(JUDGE_CONCURRENCY)

        async def one(post: Post) -> Any:
            async with gate:
                if self._stopping:
                    return _SKIPPED
                state = build_metadata_state(plan.brief, post)
                return await self._judge_one(run, post.id, PASS_ONE, state, pack, rstate)

        try:
            results = await self._settle(one(p) for p in posts)
        finally:
            self._save_counters(run)
        # Only reached when every post was judged or failed: never keep on a partial pass.
        ok = [r for r in results if isinstance(r, JudgeResult)]
        kept = pass_one_keep(ok, pack)
        metadata_ids = set(pack.metadata_pass)
        for r in ok:
            self.events.emit(
                "pass_one_judged",
                Stage.pass_one,
                {
                    "judge": r.model_dump(mode="json"),
                    "kept": r.post_id in kept,
                    "composite": composite(r, pack, question_ids=metadata_ids),
                },
            )
        rstate.pass_one_kept = sorted(kept)
        rstate.pass_one_dropped = sorted({r.post_id for r in ok} - kept)
        save_state(self.paths, rstate)
        run.counters.pass_one_kept = len(kept)
        self._save_counters(run)

    # ---- extracting ---------------------------------------------------------------------

    async def _fetch_media(self, run: Run, post: Post) -> Post:
        platform = post.platform.value
        adapter = self.adapters.get(platform)
        if adapter is None:
            self._error(run, f"adapter.{platform}", "no adapter to fetch media", post_id=post.id)
            return post
        try:
            fetched = await asyncio.to_thread(
                adapter.fetch_media, post, self.paths.media_dir(post.id)
            )
        except Exception as exc:  # MediaDownloadError or any adapter failure: recoverable (C.6)
            self._error(run, f"adapter.{platform}", f"fetch_media failed: {exc!r}", post.id)
            return post
        self.repo.upsert_post(self.run_id, fetched)
        return fetched

    async def _extract(self, run: Run) -> None:
        rstate = load_state(self.paths)
        gate = asyncio.Semaphore(EXTRACT_CONCURRENCY)
        done = set(rstate.extracted) | set(rstate.judge_failed)
        todo = [pid for pid in rstate.pass_one_kept if pid not in done]

        async def one(pid: str) -> Any:
            async with gate:
                if self._stopping:
                    return _SKIPPED
                post = await self._fetch_media(run, self.repo.get_post(self.run_id, pid))
                try:
                    evidence = await asyncio.to_thread(
                        extract_evidence, post, self.paths, self.asr, self.ocr, self.frames
                    )
                except Exception as exc:
                    self._error(run, "evidence.extract", f"extraction failed: {exc!r}", pid)
                    evidence = _empty_evidence(post)
                self.repo.save_evidence(self.run_id, evidence)
                self.events.emit(
                    "evidence_ready",
                    Stage.extracting,
                    {"post_id": pid, "evidence": evidence.model_dump(mode="json")},
                )
                rstate.extracted.append(pid)
                save_state(self.paths, rstate)
                return None

        await self._settle(one(pid) for pid in todo)

    # ---- pass two -----------------------------------------------------------------------

    async def _pass_two(self, run: Run) -> None:
        plan = self._plan()
        pack = self._pack(plan)
        rstate = load_state(self.paths)
        gate = asyncio.Semaphore(JUDGE_CONCURRENCY)

        async def one(pid: str) -> Any:
            async with gate:
                if self._stopping:
                    return _SKIPPED
                if pid in rstate.judge_failed:
                    return None
                if self.repo.get_judge_result(self.run_id, pid, PASS_TWO) is not None:
                    return None  # judged before a pause or crash
                post = self.repo.get_post(self.run_id, pid)
                evidence = self.repo.get_evidence(self.run_id, pid)
                state, truncated = build_state(plan.brief, post, evidence)
                if truncated and evidence is not None and not evidence.truncated:
                    evidence = evidence.model_copy(update={"truncated": True})  # B.3
                    self.repo.save_evidence(self.run_id, evidence)
                result = await self._judge_one(run, pid, PASS_TWO, state, pack, rstate)
                if result is None:
                    return None
                run.counters.judged += 1
                self._save_counters(run)
                self.events.emit(
                    "judged",
                    Stage.pass_two,
                    {"judge": result.model_dump(mode="json"), "composite": composite(result, pack)},
                )
                return None

        await self._settle(one(pid) for pid in rstate.pass_one_kept)

    def _pass_two_results(self) -> list[JudgeResult]:
        failed = set(load_state(self.paths).judge_failed)
        results = self.repo.list_judge_results(self.run_id, PASS_TWO)
        return [r for r in results if r.post_id not in failed]

    # ---- selecting ----------------------------------------------------------------------

    def _store_selection(self, run: Run, selection: Selection) -> None:
        self.repo.save_selection(self.run_id, selection)
        run.counters.shortlisted = len(selection.shortlist)
        run.counters.review = len(selection.review)

    async def _select(self, run: Run) -> None:
        pack = self._pack(self._plan())
        selection = select(self._pass_two_results(), pack)
        self._store_selection(run, selection)
        self._save_counters(run)
        self.events.emit("selected", Stage.selecting, selection.model_dump(mode="json"))

    async def reselect(self, weights_override: dict[str, float]) -> Selection:
        """Re-run `select` on the stored pass-two results with other weights. No Jev calls,
        no new report; emits a second `selected`. Elapsed time is left as it was."""
        if self.repo.get_selection(self.run_id) is None:
            raise RuntimeError(f"run {self.run_id} has no selection to redo yet")
        pack = self._pack(self._plan())
        selection = select(self._pass_two_results(), pack, weights_override=weights_override)
        run = self._run()
        self._store_selection(run, selection)
        self.repo.save_run(run)
        self.events.emit("selected", run.stage, selection.model_dump(mode="json"))
        return selection

    # ---- explaining ---------------------------------------------------------------------

    @staticmethod
    def _aggregates(results: list[JudgeResult]) -> dict[str, dict[str, int]]:
        """Choice label counts per question over every pass-two result."""
        agg: dict[str, dict[str, int]] = {}
        for r in results:
            for qid, answer in r.answers.items():
                if answer.type == "choice":
                    labels = agg.setdefault(qid, {})
                    labels[str(answer.value)] = labels.get(str(answer.value), 0) + 1
        return agg

    async def _explain(self, run: Run) -> None:
        plan = self._plan()
        selection = self.repo.get_selection(self.run_id)
        if selection is None:
            raise ExplainError("no selection to explain")
        if not selection.shortlist:  # fail before any backend call: an empty report costs money
            raise ExplainError("nothing to explain: no post reached the shortlist")
        results = self._pass_two_results()
        by_id = {r.post_id: r for r in results}
        shortlist = list(selection.shortlist)
        posts = [self.repo.get_post(self.run_id, pid) for pid in shortlist]
        evidence = {
            pid: ev
            for pid in shortlist
            if (ev := self.repo.get_evidence(self.run_id, pid)) is not None
        }
        packet = build_explain_packet(
            self.run_id,
            plan.brief,
            posts,
            evidence,
            {pid: by_id[pid] for pid in shortlist if pid in by_id},
            self._aggregates(results),
        )
        try:
            report = await asyncio.to_thread(self.explain_backend.explain, packet)
        except ExplainError:
            raise
        except Exception as exc:  # a backend crash fails the run like a bad report
            raise ExplainError(f"explain backend failed: {exc!r}") from exc
        report = report.model_copy(update={"run_id": self.run_id})
        unknown = validate_report_citations(report, set(shortlist))
        if unknown:
            raise ExplainError(f"report cites unknown post ids: {unknown}")
        self.repo.save_report(self.run_id, report)
        self.events.emit("explained", Stage.explaining, {"report": report.model_dump(mode="json")})
