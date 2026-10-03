"""Turn a brief into an approvable Plan via the explain backend, then enforce invariants in code.

The backend proposes topic, audience, persona, queries and persona criteria. The planner owns
`run_id`, `quantities`, `rubric_pack`, `brief.text` and `brief.language_hint`.
"""

from __future__ import annotations

from pathlib import Path

from clipsieve.explain.base import ExplainBackend, ExplainError, RubricPackSummary
from clipsieve.judge.rubric import PERSONA_FIT, PERSONA_LEVELS, find_pack, load_pack
from clipsieve.logging import get_logger
from clipsieve.models import Brief, Plan, Query, ScoreQuestion

log = get_logger(__name__)

ZH_PLATFORMS = frozenset({"xiaohongshu", "douyin", "bilibili"})
LOCAL = "local"


def default_lang(platform: str, language_hint: str | None) -> str:
    if platform in ZH_PLATFORMS:
        return "zh"
    return language_hint or "en"


def pack_summaries(rubrics_dir: Path) -> list[RubricPackSummary]:
    out: list[RubricPackSummary] = []
    for path in sorted(Path(rubrics_dir).glob("*.yaml")):
        pack = load_pack(path)
        out.append(
            RubricPackSummary(
                name=pack.name,
                description=f"{pack.name} v{pack.version}",
                question_ids=list(pack.questions),
            )
        )
    return out


def _valid_criteria(criteria: list[str]) -> bool:
    return len(criteria) == PERSONA_LEVELS and all(c.strip() for c in criteria)


def build_plan(
    run_id: str,
    brief_text: str,
    platforms: list[str],
    quantities: dict[str, int],
    rubric_pack: str,
    language_hint: str | None,
    backend: ExplainBackend,
    rubrics_dir: Path,
) -> Plan:
    missing = [p for p in platforms if p not in quantities]
    if missing:
        raise ValueError(f"missing quantities for platforms: {missing}")
    pack = find_pack(rubric_pack, rubrics_dir)  # the user's choice wins; unknown raises

    seed = Brief(text=brief_text, topic="", audience="", persona="", language_hint=language_hint)
    draft = backend.plan(seed, pack_summaries(rubrics_dir), list(platforms))

    brief = draft.brief.model_copy(update={"text": brief_text, "language_hint": language_hint})

    queries: list[Query] = []
    for q in draft.queries:
        if q.platform not in platforms:
            continue
        lang = q.lang.strip() or default_lang(q.platform, language_hint)
        queries.append(q.model_copy(update={"lang": lang}))
    for platform in platforms:
        # A `local` query is a folder or CSV path, never a search: do not invent one.
        if platform == LOCAL or any(q.platform == platform for q in queries):
            continue
        queries.append(
            Query(
                platform=platform,
                query=brief.topic or brief_text,
                lang=default_lang(platform, language_hint),
            )
        )
        log.info("plan_query_filled", platform=platform)

    criteria = list(draft.persona_fit_criteria)
    if not _valid_criteria(criteria):
        persona_q = pack.questions.get(PERSONA_FIT)
        fallback = list(persona_q.criteria) if isinstance(persona_q, ScoreQuestion) else []
        if not _valid_criteria(fallback):
            raise ExplainError(
                f"backend returned {len(criteria)} persona_fit_criteria and pack "
                f"{pack.name!r} has no {PERSONA_LEVELS}-level persona_fit fallback"
            )
        log.warning("plan_persona_criteria_fallback", got=len(criteria), pack=pack.name)
        criteria = fallback

    return Plan(
        run_id=run_id,
        brief=brief,
        queries=queries,
        quantities={p: int(quantities[p]) for p in platforms},
        rubric_pack=pack.name,
        persona_fit_criteria=criteria,
        approved_at=None,
    )
