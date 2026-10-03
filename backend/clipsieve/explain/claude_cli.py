"""Explain backend that shells out to `claude -p` with structured output.

Individual-use backend: runs on the user's own Claude Code login.
Never pass --bare (it drops OAuth).
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from clipsieve.explain.base import (
    PROMPTS_DIR,
    ExplainBackend,
    ExplainError,
    ExplainPacket,
    PlanRequest,
    RubricPackSummary,
    cli_payload,
    validate_report_citations,
)
from clipsieve.logging import get_logger
from clipsieve.models import Brief, Plan, Report

log = get_logger(__name__)

PLAN_TASK = "Create the research plan for the brief in the JSON on stdin."
EXPLAIN_TASK = "Analyze the shortlisted posts in the JSON on stdin and return the report."

_TAIL = 500


def _schema_errors(exc: ValidationError) -> str:
    """The first three validation errors as `loc: msg`, without echoing the input."""
    return "; ".join(
        f"{'.'.join(str(part) for part in err['loc']) or '<root>'}: {err['msg']}"
        for err in exc.errors()[:3]
    )


class ClaudeCliBackend(ExplainBackend):
    def __init__(
        self,
        bin: str,
        max_budget_usd: float,
        model: str = "opus",
        effort: str = "high",
        timeout_s: int = 900,
    ) -> None:
        self._bin = bin
        self._budget = max_budget_usd
        self._model = model
        self._effort = effort
        self._timeout = timeout_s

    def _argv(self, prompt_file: Path, schema: dict[str, Any], task: str) -> list[str]:
        return [
            self._bin,
            "-p",
            "--model",
            self._model,
            "--effort",
            self._effort,
            "--tools",
            "",
            "--strict-mcp-config",
            "--setting-sources",
            "",
            "--no-session-persistence",
            "--system-prompt-file",
            str(prompt_file),
            "--output-format",
            "json",
            "--json-schema",
            json.dumps(schema, ensure_ascii=False),
            "--max-budget-usd",
            str(self._budget),
            task,
        ]

    def _invoke(self, mode: str, schema_model: type[BaseModel], task: str, payload: str) -> Any:
        """Run `claude -p` once and return the envelope's `structured_output`."""
        argv = self._argv(PROMPTS_DIR / f"{mode}.md", schema_model.model_json_schema(), task)
        try:
            proc = subprocess.run(
                argv,
                input=payload,
                capture_output=True,
                text=True,
                timeout=self._timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ExplainError(f"claude -p timed out after {self._timeout}s") from exc
        except OSError as exc:
            raise ExplainError(f"cannot run claude binary {self._bin!r}: {exc}") from exc
        stderr_tail = proc.stderr.strip()[-_TAIL:]
        if proc.returncode != 0 and not proc.stdout.strip():
            raise ExplainError(f"claude -p exited {proc.returncode}: {stderr_tail}")
        try:
            envelope = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise ExplainError(
                f"claude -p returned non-JSON (exit {proc.returncode}): "
                f"{proc.stdout[:200]!r}; stderr: {stderr_tail}"
            ) from exc
        if not isinstance(envelope, dict):
            raise ExplainError(f"claude -p returned a non-object envelope: {proc.stdout[:200]!r}")
        if envelope.get("is_error"):
            detail = envelope.get("result") or envelope.get("errors") or envelope.get("subtype")
            raise ExplainError(f"claude -p error: {str(detail)[:_TAIL]!r}")
        if proc.returncode != 0:
            raise ExplainError(f"claude -p exited {proc.returncode}: {stderr_tail}")
        structured = envelope.get("structured_output")
        if structured is None:
            try:
                structured = json.loads(envelope.get("result") or "")
            except (TypeError, json.JSONDecodeError) as exc:
                raise ExplainError("claude -p returned no structured_output") from exc
        log.info(
            "claude_cli_done",
            mode=mode,
            cost_usd=envelope.get("total_cost_usd"),
            duration_ms=envelope.get("duration_ms"),
        )
        return structured

    def _structured[M: BaseModel](
        self,
        mode: str,
        schema_model: type[M],
        base_task: str,
        payload: str,
        unknown_ids: Callable[[M], list[str]] | None = None,
    ) -> M:
        """Call the CLI, validate, and retry once on a schema failure or an unknown citation."""
        task = base_task
        for attempt in (1, 2):
            data = self._invoke(mode, schema_model, task, payload)
            try:
                result = schema_model.model_validate(data)
            except ValidationError as exc:
                problem = f"failed schema validation: {_schema_errors(exc)}"
                fix = f"Return a valid {schema_model.__name__}."
            else:
                unknown = unknown_ids(result) if unknown_ids else []
                if not unknown:
                    return result
                problem = f"cited unknown post ids: {', '.join(unknown)}"
                fix = "Cite only ids present in `posts`."
            if attempt == 2:
                raise ExplainError(f"{mode} {problem} (after one retry)")
            log.warning("claude_cli_retry", mode=mode, problem=problem)
            task = f"{base_task} The previous attempt {problem}. {fix}"
        raise ExplainError("unreachable")

    def plan(self, brief: Brief, packs: list[RubricPackSummary], platforms: list[str]) -> Plan:
        body = PlanRequest(brief=brief, packs=packs, platforms=platforms)
        return self._structured("plan", Plan, PLAN_TASK, cli_payload("plan", body))

    def explain(self, packet: ExplainPacket) -> Report:
        known = {p.id for p in packet.posts}
        return self._structured(
            "explain",
            Report,
            EXPLAIN_TASK,
            cli_payload("explain", packet),
            unknown_ids=lambda report: validate_report_citations(report, known),
        )
