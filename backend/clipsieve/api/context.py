"""Process-wide wiring for the API: settings, repository, adapters and one shared backend each.

`build_context(settings)` picks fake or real backends; `get_context()` is the FastAPI dependency.
One `Runner` per run id is cached in `runners`, and the background task driving that run lives in
`tasks[run_id]`. `run()` is serialised per run by `lock_for(run_id)`.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

from clipsieve.adapters.base import Adapter
from clipsieve.adapters.registry import load_adapters
from clipsieve.config import Settings, ensure_creator_salt, get_settings
from clipsieve.evidence.asr import ASR, FakeASR
from clipsieve.evidence.frames import FakeFrames, FrameExtractor
from clipsieve.evidence.ocr import OCR, FakeOCR
from clipsieve.explain.base import ExplainBackend, get_backend
from clipsieve.judge.base import Judge
from clipsieve.logging import get_logger
from clipsieve.pipeline.runner import Runner
from clipsieve.store.db import get_engine, init_db
from clipsieve.store.repo import RunRepository

log = get_logger(__name__)

RUBRICS_DIR_DEFAULT = Path(__file__).resolve().parents[3] / "rubrics"
# backend/tests/fixtures: what fake mode serves when CLIPSIEVE_FIXTURE_DIR is unset (E.7 / D.2).
DEFAULT_FIXTURE_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures"


@dataclass
class AppContext:
    settings: Settings
    repo: RunRepository
    adapters: dict[str, Adapter]
    judge: Judge
    explain: ExplainBackend
    asr: ASR
    ocr: OCR
    frames: FrameExtractor
    rubrics_dir: Path
    runners: dict[str, Runner] = field(default_factory=dict)
    tasks: dict[str, asyncio.Task[None]] = field(default_factory=dict)
    # Run ids with a pause asked for and not yet resumed; see `api.runs._drive`.
    pause_requests: set[str] = field(default_factory=set)
    locks: dict[str, asyncio.Lock] = field(default_factory=dict)

    def runner_for(self, run_id: str) -> Runner:
        """The one Runner for this run id. Building it emits `run_created` on an empty log."""
        if run_id not in self.runners:
            self.runners[run_id] = Runner(
                run_id=run_id,
                settings=self.settings,
                repo=self.repo,
                adapters=self.adapters,
                judge=self.judge,
                explain=self.explain,
                asr=self.asr,
                ocr=self.ocr,
                frames=self.frames,
                rubrics_dir=self.rubrics_dir,
            )
        return self.runners[run_id]

    def lock_for(self, run_id: str) -> asyncio.Lock:
        return self.locks.setdefault(run_id, asyncio.Lock())

    def busy(self, run_id: str) -> bool:
        """True while a planning or pipeline task for this run is still running."""
        task = self.tasks.get(run_id)
        return task is not None and not task.done()


def build_context(settings: Settings) -> AppContext:
    fake = settings.clipsieve_explain_backend == "fake"
    if fake and settings.clipsieve_fixture_dir is None:
        # E.7 / D.2: fake mode means the repo fixtures unless told otherwise.
        settings = settings.model_copy(update={"clipsieve_fixture_dir": DEFAULT_FIXTURE_DIR})
    # A.12: create the salt once, up front, and hand every adapter the same value.
    salt = ensure_creator_salt(settings)
    settings = settings.model_copy(update={"clipsieve_creator_salt": salt})

    engine = get_engine(settings.clipsieve_data_dir)
    init_db(engine)
    repo = RunRepository(settings.clipsieve_data_dir, engine)
    if fake:
        from clipsieve.judge.recorded import RecordedJudge

        judge: Judge = RecordedJudge(settings.clipsieve_fixture_dir or DEFAULT_FIXTURE_DIR)
        asr: ASR = FakeASR()
        ocr: OCR = FakeOCR()
        frames: FrameExtractor = FakeFrames()
    else:
        # Lazy: a missing optional extra fails at first use, not at import.
        from clipsieve.evidence.asr import WhisperASR
        from clipsieve.evidence.frames import FfmpegFrames
        from clipsieve.evidence.ocr import PaddleOCRBackend
        from clipsieve.judge.typesafe_client import TypeSafeJudge

        judge = TypeSafeJudge(settings.typesafe_api_key)
        asr, ocr, frames = WhisperASR(), PaddleOCRBackend(), FfmpegFrames()
    ctx = AppContext(
        settings=settings,
        repo=repo,
        adapters=load_adapters(settings),
        judge=judge,
        explain=get_backend(settings, settings.clipsieve_fixture_dir),
        asr=asr,
        ocr=ocr,
        frames=frames,
        rubrics_dir=RUBRICS_DIR_DEFAULT,
    )
    log.info(
        "api_context_built",
        explain_backend=settings.clipsieve_explain_backend,
        fixture_dir=str(settings.clipsieve_fixture_dir) if settings.clipsieve_fixture_dir else None,
        platforms=sorted(ctx.adapters),
    )
    return ctx


_CONTEXT: AppContext | None = None


def set_context(ctx: AppContext) -> None:
    global _CONTEXT
    _CONTEXT = ctx


def get_context() -> AppContext:
    """FastAPI dependency. Builds the context from `get_settings()` on first use."""
    global _CONTEXT
    if _CONTEXT is None:
        _CONTEXT = build_context(get_settings())
    return _CONTEXT
