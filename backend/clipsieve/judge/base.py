"""Judge protocol shared by the TypeSafe client and the recorded fake."""

from __future__ import annotations

from typing import Protocol

from clipsieve.models import JudgeResult, Question

JEV_USD_PER_MILLION_INPUT = 0.042


def cost_usd(input_tokens: int) -> float:
    return input_tokens / 1_000_000 * JEV_USD_PER_MILLION_INPUT


class JudgeFailed(Exception):
    def __init__(self, post_id: str, attempts: int, cause: BaseException | None = None) -> None:
        super().__init__(f"judge failed for {post_id} after {attempts} attempt(s): {cause!r}")
        self.post_id = post_id
        self.attempts = attempts
        self.cause = cause


class Judge(Protocol):
    async def judge(
        self,
        post_id: str,
        pass_name: str,
        state: dict,
        questions: dict[str, Question],
        model: str,
    ) -> JudgeResult: ...
