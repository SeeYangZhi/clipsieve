import pytest

from clipsieve.explain.base import ExplainPacket
from clipsieve.explain.claude_api import ClaudeApiBackend
from clipsieve.models import Brief


@pytest.mark.xfail(
    reason="claude_api backend is a v0.2 follow-up; contract pinned here",
    raises=NotImplementedError,
    strict=True,
)
def test_claude_api_explain_contract(fixture_posts):
    backend = ClaudeApiBackend(api_key="unused")
    packet = ExplainPacket(
        brief=Brief(text="b", topic="", audience="", persona=""),
        posts=fixture_posts[:1],
        evidence={},
        judge={},
        aggregates={},
        keyframes={},
    )
    report = backend.explain(packet)
    assert [c.post_id for c in report.clips] == [fixture_posts[0].id]


def test_claude_api_plan_raises_not_implemented():
    backend = ClaudeApiBackend(api_key="unused")
    with pytest.raises(NotImplementedError, match="v0.2 follow-up to plan 03; use claude_cli"):
        backend.plan(Brief(text="b", topic="", audience="", persona=""), [], ["youtube"])
