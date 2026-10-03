"""Claude API explain backend.

Stub in v0.1; the contract test in tests/explain pins the packet format.
"""

from __future__ import annotations

from clipsieve.explain.base import ExplainBackend, ExplainPacket, RubricPackSummary
from clipsieve.models import Brief, Plan, Report

MESSAGE = "claude_api backend is a v0.2 follow-up to plan 03; use claude_cli"


class ClaudeApiBackend(ExplainBackend):
    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def plan(self, brief: Brief, packs: list[RubricPackSummary], platforms: list[str]) -> Plan:
        raise NotImplementedError(MESSAGE)

    def explain(self, packet: ExplainPacket) -> Report:
        raise NotImplementedError(MESSAGE)
