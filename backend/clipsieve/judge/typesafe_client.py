"""TypeSafe Jev judge: one batched system_one request per post, bounded concurrency, backoff.

429 and 529 are retried here (`0.5 s * 2^n` capped at 8 s plus jitter, or the server's
Retry-After when longer, up to 30 s). The SDK client keeps its own retries for connection errors,
timeouts and the other 408/5xx statuses, inside one of our attempts, but never for 429 or 529.
"""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from typing import Any

from typesafe_sdk import AsyncTypeSafeClient, RetryPolicy

from clipsieve.judge.base import Judge, JudgeFailed
from clipsieve.judge.rubric import from_typesafe, to_typesafe
from clipsieve.logging import get_logger
from clipsieve.models import JudgeResult, Question

log = get_logger(__name__)

RETRYABLE_STATUS = {429, 529}
BASE_BACKOFF_S = 0.5
MAX_BACKOFF_S = 8.0
JITTER_S = 0.1
MAX_RETRY_AFTER_S = 30.0
# SDK defaults (2 retries, connection/timeout errors, 408 and 5xx) minus the statuses we own.
SDK_RETRY = RetryPolicy(http_statuses=RetryPolicy().http_statuses - RETRYABLE_STATUS)


def _is_retryable(exc: BaseException) -> bool:
    status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    if status in RETRYABLE_STATUS:
        return True
    name = type(exc).__name__.lower()
    return "ratelimit" in name or "overloaded" in name


def _backoff_s(attempt: int, exc: BaseException) -> float:
    delay = min(MAX_BACKOFF_S, BASE_BACKOFF_S * (2 ** (attempt - 1))) + random.uniform(0, JITTER_S)
    retry_after_ms = getattr(exc, "retry_after_ms", None)  # TypeSafeRateLimitError, parsed
    if retry_after_ms:
        delay = max(delay, min(MAX_RETRY_AFTER_S, retry_after_ms / 1000))
    return delay


def _default_client_factory(api_key: str) -> Callable[[], Any]:
    def factory() -> Any:
        return AsyncTypeSafeClient(api_key=api_key, retry=SDK_RETRY)

    return factory


class TypeSafeJudge(Judge):
    def __init__(
        self,
        api_key: str,
        concurrency: int = 16,
        max_retries: int = 5,
        client_factory: Callable[[], Any] | None = None,
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._factory = client_factory or _default_client_factory(api_key)
        self._client: Any = None
        self._sem = asyncio.Semaphore(concurrency)
        # Total attempts per post (5 = at most 5 requests), unlike the SDK's
        # `RetryPolicy.max_retries`, which counts retries after the first request.
        self._max_retries = max_retries
        self._sleep = sleeper

    def _get_client(self) -> Any:
        if self._client is None:
            self._client = self._factory()
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and hasattr(self._client, "aclose"):
            await self._client.aclose()
        self._client = None

    async def judge(
        self,
        post_id: str,
        pass_name: str,
        state: dict,
        questions: dict[str, Question],
        model: str,
    ) -> JudgeResult:
        ts_questions = {qid: to_typesafe(q) for qid, q in questions.items()}
        attempts = 0
        async with self._sem:
            while True:
                attempts += 1
                started = time.perf_counter()
                try:
                    response = await self._get_client().system_one(
                        state=state, questions=ts_questions, model=model
                    )
                except Exception as exc:
                    if _is_retryable(exc) and attempts < self._max_retries:
                        delay = _backoff_s(attempts, exc)
                        log.warning(
                            "jev_retry",
                            post_id=post_id,
                            attempt=attempts,
                            error=type(exc).__name__,
                            delay_s=round(delay, 2),
                        )
                        await self._sleep(delay)
                        continue
                    raise JudgeFailed(post_id, attempts, exc) from exc
                latency_ms = int((time.perf_counter() - started) * 1000)
                try:
                    answers = {qid: from_typesafe(qid, q, response) for qid, q in questions.items()}
                except (KeyError, TypeError, ValueError) as exc:  # an answer missing or malformed
                    raise JudgeFailed(post_id, attempts, exc) from exc
                usage = getattr(response, "usage", None)
                return JudgeResult(
                    post_id=post_id,
                    pass_name=pass_name,
                    model=str(getattr(response, "model", model)),
                    input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
                    latency_ms=latency_ms,
                    answers=answers,
                )
