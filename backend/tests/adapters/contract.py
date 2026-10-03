"""Adapter contract. Every adapter, including contrib ones, must pass run_adapter_contract."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from clipsieve.adapters.base import Adapter
from clipsieve.models import Post, Query
from clipsieve.store.paths import RunPaths, safe_post_filename

CREATOR_HASH = re.compile(r"^[0-9a-f]{64}$")


def relocate_raw(post: Post, paths: RunPaths) -> Post:
    """What the Runner does before `fetch_media`: move the raw payload into the run and rewrite
    `raw_ref` to the run-relative `raw/<safe_post_id>.json` (overview Addendum B.10)."""
    target = paths.raw_path(post.id, "json")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(post.raw_ref, target)
    return post.model_copy(update={"raw_ref": f"raw/{safe_post_filename(post.id)}.json"})


def run_adapter_contract(
    adapter: Adapter, query: Query, tmp_path: Path, limit: int = 3
) -> list[Post]:
    assert isinstance(adapter.platform, str) and adapter.platform

    posts = list(adapter.search([query], limit))
    assert posts, "search must yield at least one post for the fixture query"
    assert len(posts) <= limit
    ids = [p.id for p in posts]
    assert len(ids) == len(set(ids)), f"post ids must be unique: {ids}"

    for post in posts:
        # valid model round trip
        Post.model_validate(post.model_dump(mode="json"))
        assert post.platform == adapter.platform
        assert post.id.startswith(f"{adapter.platform}:")

        raw = Path(post.raw_ref)
        assert raw.is_file(), f"raw_ref must resolve to a file: {post.raw_ref}"
        json.loads(raw.read_text(encoding="utf-8"))

        assert CREATOR_HASH.fullmatch(post.creator_hash), "creator_hash must be 64 hex chars"
        assert post.creator_hash not in post.raw_ref
        assert post.creator_hash != (post.creator_display or "")

        assert len(post.comments) <= 50
        for m in post.media:
            assert m.local_path is None, "search must not download media"

    # The Runner relocates every raw payload before any fetch_media call, so fetch_media must
    # never read raw_ref or the incoming file.
    paths = RunPaths(tmp_path / "contract-data", "contract-run")
    paths.ensure()
    relocated = [relocate_raw(p, paths) for p in posts]
    for before, after in zip(posts, relocated, strict=True):
        assert not Path(before.raw_ref).exists(), "the incoming raw file has been moved"
        assert (paths.root / after.raw_ref).is_file()

    first = relocated[0]
    dest = paths.media_dir(first.id)
    dest.mkdir(parents=True, exist_ok=True)
    once = adapter.fetch_media(first, dest)
    twice = adapter.fetch_media(once, dest)
    paths_once = [m.local_path for m in once.media]
    paths_twice = [m.local_path for m in twice.media]
    assert paths_once == paths_twice, "fetch_media must be idempotent"
    for p in paths_once:
        assert p is not None
        assert not Path(p).is_absolute(), f"local_path must be relative to dest: {p}"
        assert (dest / p).is_file(), f"local_path must be relative to dest: {p}"
    assert once.raw_ref == first.raw_ref, "fetch_media must not touch raw_ref"
    return posts
