"""Adapter contract. Every adapter, including contrib ones, must pass run_adapter_contract."""

from __future__ import annotations

import json
from pathlib import Path

from clipsieve.adapters.base import Adapter
from clipsieve.models import Post, Query


def run_adapter_contract(
    adapter: Adapter, query: Query, tmp_path: Path, limit: int = 3
) -> list[Post]:
    assert isinstance(adapter.platform, str) and adapter.platform

    posts = list(adapter.search([query], limit))
    assert posts, "search must yield at least one post for the fixture query"
    assert len(posts) <= limit

    for post in posts:
        # valid model round trip
        Post.model_validate(post.model_dump(mode="json"))
        assert post.platform == adapter.platform
        assert post.id.startswith(f"{adapter.platform}:")

        raw = Path(post.raw_ref)
        assert raw.is_file(), f"raw_ref must resolve to a file: {post.raw_ref}"
        json.loads(raw.read_text(encoding="utf-8"))

        assert len(post.creator_hash) == 64
        assert post.creator_hash not in post.raw_ref
        assert post.creator_hash != (post.creator_display or "")

        assert len(post.comments) <= 50
        for m in post.media:
            assert m.local_path is None, "search must not download media"

    first = posts[0]
    dest = tmp_path / "media"
    dest.mkdir()
    once = adapter.fetch_media(first, dest)
    twice = adapter.fetch_media(once, dest)
    paths_once = [m.local_path for m in once.media]
    paths_twice = [m.local_path for m in twice.media]
    assert paths_once == paths_twice, "fetch_media must be idempotent"
    for p in paths_once:
        assert p is not None
        assert (dest / p).is_file(), f"local_path must be relative to dest: {p}"
    return posts
