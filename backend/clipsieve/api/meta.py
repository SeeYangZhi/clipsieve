"""Adapters, rubric packs and per-post media files."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from clipsieve.api.runs import Ctx, get_run_or_404
from clipsieve.explain.base import RubricPackSummary
from clipsieve.logging import get_logger
from clipsieve.planner.plan import pack_summaries

log = get_logger(__name__)
router = APIRouter()


class AdapterStatus(BaseModel):
    platform: str
    healthy: bool
    message: str


@router.get("/adapters", response_model=list[AdapterStatus], response_model_exclude_none=True)
async def adapters(ctx: Ctx) -> list[AdapterStatus]:
    out: list[AdapterStatus] = []
    for platform, adapter in sorted(ctx.adapters.items()):
        try:
            health = await asyncio.to_thread(adapter.healthcheck)
        except Exception as exc:  # a plugin's healthcheck must not break the listing
            log.warning("adapter_healthcheck_failed", platform=platform, error=repr(exc))
            out.append(AdapterStatus(platform=platform, healthy=False, message=repr(exc)))
            continue
        out.append(AdapterStatus(platform=platform, healthy=health.ok, message=health.message))
    return out


@router.get("/rubrics", response_model=list[RubricPackSummary], response_model_exclude_none=True)
async def rubrics(ctx: Ctx) -> list[RubricPackSummary]:
    return pack_summaries(ctx.rubrics_dir)


@router.get("/runs/{run_id}/media/{post_id}/{filename:path}", response_model_exclude_none=True)
async def media(run_id: str, post_id: str, filename: str, ctx: Ctx) -> FileResponse:
    """`post_id` arrives URL-decoded (`local%3Afx-001` -> `local:fx-001`). `filename` may name
    a file under the post's media dir (`thumb.jpg`, `frames/<name>`); anything resolving outside
    that dir (`..`, an absolute path, a post id of `..`) is 404."""
    get_run_or_404(ctx, run_id)
    paths = ctx.repo.paths(run_id)
    media_root = (paths.root / "media").resolve()
    base = paths.media_dir(post_id).resolve()
    target = (base / filename).resolve()
    if base.parent != media_root or not target.is_relative_to(base) or not target.is_file():
        raise HTTPException(404, "no such media")
    return FileResponse(target)
