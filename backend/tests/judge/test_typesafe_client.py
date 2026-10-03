import asyncio
import dataclasses
import json
from pathlib import Path

import httpx2
import pytest
from typesafe_sdk import (
    AsyncTypeSafeClient,
    Choice,
    Noul,
    Score,
    SystemOneResponse,
    TypeSafeInternalServerError,
    TypeSafeRateLimitError,
    TypeSafeUnprocessableEntityError,
)

from clipsieve.judge import typesafe_client
from clipsieve.judge.base import JudgeFailed, cost_usd
from clipsieve.judge.rubric import load_pack, questions_for_pass, to_typesafe
from clipsieve.judge.typesafe_client import TypeSafeJudge

RUBRICS = Path(__file__).resolve().parents[3] / "rubrics"


class RateLimited(Exception):
    status_code = 429


def response_payload(questions):
    """A `/v1/systemone` body answering every question, shaped by its real SDK primitive."""
    answers = {}
    for qid, q in questions.items():
        if isinstance(q, Choice):
            label = next(iter(q.criteria))
            answers[qid] = {
                "type": "choice",
                "choice": label,
                "confidence": 0.9,
                "probabilities": {label: 0.9},
            }
        elif isinstance(q, Score):
            answers[qid] = {
                "type": "score",
                "score": 3.0,
                "confidence": 1.0,
                "legend": {str(i): text for i, text in enumerate(q.criteria)},
                "probabilities": {"3": 1.0},
            }
        elif isinstance(q, Noul):
            answers[qid] = {"type": "noul", "noul": 0.1}
        else:
            raise AssertionError(f"{qid} is not a TypeSafe primitive: {q!r}")
    return {
        "model": "jev-1.13.0",
        "usage": {"input_tokens": 1234, "output_tokens": 0},
        "answers": answers,
    }


def make_response(questions):
    return SystemOneResponse.model_validate_json(json.dumps(response_payload(questions)))


class FakeClient:
    """Mimics `AsyncTypeSafeClient.system_one(state, questions, *, model)` and `aclose()`.

    `fail_plan` maps post marker -> exceptions to raise before answering.
    """

    def __init__(self, fail_plan=None, drop_answers=False):
        self.calls = []
        self.in_flight = 0
        self.max_in_flight = 0
        self.closed = False
        self.drop_answers = drop_answers
        self.fail_plan = dict(fail_plan or {})

    async def system_one(self, state, questions, *, model=None):
        marker = state["post"]["id"]
        self.calls.append(marker)
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            await asyncio.sleep(0.01)
            pending = self.fail_plan.get(marker)
            if pending:
                raise pending.pop(0)
            return make_response({} if self.drop_answers else questions)
        finally:
            self.in_flight -= 1

    async def aclose(self):
        self.closed = True


def pack_questions(pass_name):
    return questions_for_pass(load_pack(RUBRICS / "creator-hooks-v1.yaml"), pass_name)


def state_for(post_id):
    return {"brief": {"topic": "x"}, "post": {"id": post_id, "text": {"caption": "你好 Shanghai"}}}


async def no_sleep(_s):
    await asyncio.sleep(0)


def test_cost_usd():
    assert cost_usd(1_000_000) == pytest.approx(0.042)
    assert cost_usd(0) == 0.0


async def test_judge_returns_result_with_usage_and_latency():
    client = FakeClient()
    judge = TypeSafeJudge(api_key="k", client_factory=lambda: client)
    qs = pack_questions("pass_two")
    result = await judge.judge("local:a", "pass_two", state_for("local:a"), qs, "jev-1.13.0")
    assert result.post_id == "local:a"
    assert result.pass_name.value == "pass_two"
    assert result.model == "jev-1.13.0"
    assert result.input_tokens == 1234
    assert result.latency_ms >= 0
    assert set(result.answers) == set(qs)
    assert result.answers["risky_claim"].value == 0.1
    assert client.calls == ["local:a"]  # one request, all questions batched
    await judge.aclose()
    assert client.closed


async def test_concurrency_is_bounded():
    client = FakeClient()
    judge = TypeSafeJudge(api_key="k", concurrency=4, client_factory=lambda: client)
    qs = pack_questions("pass_one")
    await asyncio.gather(
        *[
            judge.judge(f"local:{i}", "pass_one", state_for(f"local:{i}"), qs, "jev-1.13.0")
            for i in range(20)
        ]
    )
    assert client.max_in_flight == 4
    assert len(client.calls) == 20


async def test_one_post_rate_limited_others_proceed():
    """RF2: a post backing off after 429s holds one slot; every other post still completes."""
    slept = []
    others_done = asyncio.Event()

    async def sleeper(s):
        slept.append(s)
        # Back off until every other post is judged; a stall behind the 429 times out here.
        await asyncio.wait_for(others_done.wait(), timeout=2)

    client = FakeClient(fail_plan={"local:slow": [RateLimited(), RateLimited()]})
    judge = TypeSafeJudge(
        api_key="k", concurrency=4, client_factory=lambda: client, sleeper=sleeper
    )
    qs = pack_questions("pass_one")
    others = [f"local:{i}" for i in range(15)]

    async def judge_others():
        results = await asyncio.gather(
            *[judge.judge(i, "pass_one", state_for(i), qs, "jev-1.13.0") for i in others]
        )
        others_done.set()
        return results

    slow, rest = await asyncio.gather(
        judge.judge("local:slow", "pass_one", state_for("local:slow"), qs, "jev-1.13.0"),
        judge_others(),
    )
    assert slow.post_id == "local:slow"
    assert [r.post_id for r in rest] == others
    assert client.calls.count("local:slow") == 3  # two 429s then success
    assert len(slept) == 2 and slept[0] < slept[1]  # exponential


async def test_backoff_schedule_doubles_and_caps():
    slept = []

    async def sleeper(s):
        slept.append(s)

    client = FakeClient(fail_plan={"local:x": [RateLimited() for _ in range(6)]})
    judge = TypeSafeJudge(
        api_key="k", max_retries=7, client_factory=lambda: client, sleeper=sleeper
    )
    await judge.judge("local:x", "pass_one", state_for("local:x"), pack_questions("pass_one"), "m")
    base = [0.5, 1.0, 2.0, 4.0, 8.0, 8.0]
    assert len(slept) == len(base)
    for delay, floor in zip(slept, base, strict=True):
        assert floor <= delay <= floor + 0.1  # 0.5 s * 2^n, capped at 8 s, plus jitter


async def test_gives_up_after_max_retries():
    client = FakeClient(fail_plan={"local:dead": [RateLimited() for _ in range(5)]})
    judge = TypeSafeJudge(
        api_key="k", max_retries=5, client_factory=lambda: client, sleeper=no_sleep
    )
    with pytest.raises(JudgeFailed) as ei:
        await judge.judge(
            "local:dead",
            "pass_one",
            state_for("local:dead"),
            pack_questions("pass_one"),
            "jev-1.13.0",
        )
    assert ei.value.post_id == "local:dead" and ei.value.attempts == 5
    assert isinstance(ei.value.cause, RateLimited)


async def test_non_retryable_error_raises_immediately():
    class Bad(Exception):
        status_code = 422

    client = FakeClient(fail_plan={"local:bad": [Bad()]})
    judge = TypeSafeJudge(api_key="k", client_factory=lambda: client)
    with pytest.raises(JudgeFailed) as ei:
        await judge.judge(
            "local:bad",
            "pass_one",
            state_for("local:bad"),
            pack_questions("pass_one"),
            "jev-1.13.0",
        )
    assert ei.value.attempts == 1 and client.calls.count("local:bad") == 1


def sdk_error(cls, status):
    return cls(status, {"error": "slow down"}, httpx2.Headers())


@pytest.mark.parametrize(
    "error",
    [
        sdk_error(TypeSafeRateLimitError, 429),
        sdk_error(TypeSafeInternalServerError, 529),
    ],
    ids=["429", "529"],
)
async def test_real_sdk_rate_limit_and_overload_are_retried(error):
    client = FakeClient(fail_plan={"local:r": [error]})
    judge = TypeSafeJudge(api_key="k", client_factory=lambda: client, sleeper=no_sleep)
    result = await judge.judge(
        "local:r", "pass_one", state_for("local:r"), pack_questions("pass_one"), "m"
    )
    assert result.post_id == "local:r" and client.calls.count("local:r") == 2


async def test_real_sdk_validation_error_is_not_retried():
    error = sdk_error(TypeSafeUnprocessableEntityError, 422)
    client = FakeClient(fail_plan={"local:v": [error]})
    judge = TypeSafeJudge(api_key="k", client_factory=lambda: client, sleeper=no_sleep)
    with pytest.raises(JudgeFailed) as ei:
        await judge.judge(
            "local:v", "pass_one", state_for("local:v"), pack_questions("pass_one"), "m"
        )
    assert ei.value.attempts == 1 and ei.value.cause is error


async def test_missing_answer_raises_judge_failed():
    client = FakeClient(drop_answers=True)
    judge = TypeSafeJudge(api_key="k", client_factory=lambda: client)
    with pytest.raises(JudgeFailed) as ei:
        await judge.judge(
            "local:m", "pass_one", state_for("local:m"), pack_questions("pass_one"), "m"
        )
    assert ei.value.post_id == "local:m" and ei.value.attempts == 1


def install_mock_sdk(monkeypatch, handler):
    """Route the default factory's real `AsyncTypeSafeClient` through `handler`.

    The judge's own `RetryPolicy` is kept; only its backoff is zeroed so SDK retries never sleep.
    """
    built = []

    def client_with_mock_transport(**kwargs):
        if kwargs.get("retry") is not None:
            kwargs["retry"] = dataclasses.replace(kwargs["retry"], backoff_initial=0.0)
        client = AsyncTypeSafeClient(**kwargs, transport=httpx2.MockTransport(handler))
        built.append(client)
        return client

    monkeypatch.setattr(typesafe_client, "AsyncTypeSafeClient", client_with_mock_transport)
    return built


def answer_200():
    qs = {qid: to_typesafe(q) for qid, q in pack_questions("pass_two").items()}
    return httpx2.Response(200, json=response_payload(qs))


async def test_default_client_batches_one_request_and_owns_retries(monkeypatch, capsys):
    """The real SDK client over a mock transport: one POST per attempt carrying every question,
    state sent as a JSON object with literal non-ASCII, and 429/529 retried by our loop only."""
    secret = "sk-test-secret-key"
    bodies = []
    statuses = iter([429, 529, 200])

    def handler(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        bodies.append((request, body))
        status = next(statuses)
        if status != 200:
            return httpx2.Response(status, json={"error": "busy"})
        return answer_200()

    built = install_mock_sdk(monkeypatch, handler)
    slept = []

    async def sleeper(s):
        slept.append(s)

    judge = TypeSafeJudge(api_key=secret, sleeper=sleeper)
    qs = pack_questions("pass_two")
    result = await judge.judge("local:a", "pass_two", state_for("local:a"), qs, "jev-1.13.0")

    assert len(bodies) == 3 and len(slept) == 2  # our loop retried, not the SDK
    request, body = bodies[-1]
    assert request.url.path == "/v1/systemone"
    assert set(body["questions"]) == set(qs)  # every question in one request
    assert body["model"] == "jev-1.13.0"
    assert body["state"] == state_for("local:a")  # a JSON object, not a pre-serialised string
    assert "你好" in request.content.decode("utf-8")  # non-ASCII kept literal on the wire
    assert result.input_tokens == 1234 and set(result.answers) == set(qs)

    await judge.aclose()
    assert built[0]._http_client.is_closed
    out = capsys.readouterr()
    assert secret not in out.out + out.err


@pytest.mark.parametrize("blip", ["connect", "timeout", "503"])
async def test_sdk_retries_network_blips_inside_one_attempt(monkeypatch, blip):
    """Connection errors, timeouts and plain 5xx stay with the SDK's own retries: the post
    succeeds in one `judge()` call and our 429/529 backoff never runs."""
    requests = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        if len(requests) == 1:
            if blip == "connect":
                raise httpx2.ConnectError("network unreachable", request=request)
            if blip == "timeout":
                raise httpx2.ReadTimeout("read timed out", request=request)
            return httpx2.Response(503, json={"error": "unavailable"})
        return answer_200()

    install_mock_sdk(monkeypatch, handler)
    slept = []

    async def sleeper(s):
        slept.append(s)

    judge = TypeSafeJudge(api_key="k", sleeper=sleeper)
    result = await judge.judge(
        "local:a", "pass_two", state_for("local:a"), pack_questions("pass_two"), "m"
    )
    await judge.aclose()
    assert result.post_id == "local:a"
    assert len(requests) == 2 and slept == []


@pytest.mark.parametrize(
    ("retry_after_ms", "low", "high"),
    [("5000", 5.0, 5.0), ("120000", 30.0, 30.0), ("100", 0.5, 0.6)],
    ids=["server-wait", "capped-30s", "schedule-floor"],
)
async def test_rate_limit_honours_retry_after(retry_after_ms, low, high):
    error = TypeSafeRateLimitError(
        429, {"error": "slow down"}, httpx2.Headers({"retry-after-ms": retry_after_ms})
    )
    assert error.retry_after_ms == float(retry_after_ms)
    slept = []

    async def sleeper(s):
        slept.append(s)

    client = FakeClient(fail_plan={"local:r": [error]})
    judge = TypeSafeJudge(api_key="k", client_factory=lambda: client, sleeper=sleeper)
    await judge.judge("local:r", "pass_one", state_for("local:r"), pack_questions("pass_one"), "m")
    assert len(slept) == 1 and low <= slept[0] <= high  # server wait, schedule floor, 30 s cap
