"""Jev state packets: the plain dicts Jev judges, held under a CJK-aware token cap.

`build_state` truncates an over-cap state in a fixed order and always returns it for judging:
comments (sample, then top terms), then OCR from the end, then the transcript tail (the head is
the hook). Only when all of that is not enough does the post's own text give way (caption tail,
then hashtags, then title tail). Nothing here sets `Evidence.truncated`; the Runner does that from
the returned flag.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from clipsieve.evidence.comments import summarize_comments
from clipsieve.logging import get_logger
from clipsieve.models import Brief, Evidence, Post

log = get_logger(__name__)

MAX_STATE_TOKENS = 28_000
METADATA_COMMENTS = 20
METADATA_COMMENT_CHARS = 200

# Characters a tokenizer spends about one token each on.
_CJK = re.compile(
    "["
    "　-〿"  # CJK symbols and punctuation
    "぀-ヿ"  # hiragana, katakana
    "㐀-䶿"  # CJK unified ideographs extension A
    "一-鿿"  # CJK unified ideographs
    "가-힯"  # hangul syllables
    "豈-﫿"  # CJK compatibility ideographs
    "＀-￯"  # halfwidth and fullwidth forms
    "]"
)


def estimate_tokens(text: str) -> int:
    """CJK characters count one token each; everything else one token per three characters."""
    cjk = len(_CJK.findall(text))
    return cjk + (len(text) - cjk) // 3


def state_json(state: dict[str, Any]) -> str:
    """Deterministic compact JSON with non-ASCII kept literal. The token estimate is taken on it."""
    return json.dumps(state, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _fits(state: dict[str, Any]) -> bool:
    return estimate_tokens(state_json(state)) <= MAX_STATE_TOKENS


def _brief_block(brief: Brief) -> dict[str, Any]:
    return {
        "text": brief.text,
        "topic": brief.topic,
        "audience": brief.audience,
        "persona": brief.persona,
    }


def _post_block(post: Post) -> dict[str, Any]:
    block: dict[str, Any] = {
        "id": post.id,
        "platform": post.platform.value,
        "kind": post.kind.value,
        "lang": post.lang,
        "title": post.text.title,
        "caption": post.text.caption,
        "hashtags": list(post.text.hashtags),
        "posted_at": post.posted_at.isoformat() if post.posted_at else None,
        "duration_s": next((m.duration_s for m in post.media if m.duration_s is not None), None),
        "metrics": post.metrics.model_dump(mode="json", exclude_none=True),
    }
    return {k: v for k, v in block.items() if v is not None}  # optional means absent


def _largest_fitting_prefix(n: int, fits_with: Callable[[int], bool]) -> int:
    """Largest k in [0, n] with fits_with(k); 0 when none fits.

    A longer prefix never shrinks the JSON, so the estimate is monotone in k and bisection finds
    the same k as dropping one item at a time, in O(log n) serialisations.
    """
    lo, hi = 0, n
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if fits_with(mid):
            lo = mid
        else:
            hi = mid - 1
    return lo


def _trim_list(state: dict[str, Any], items: list[Any]) -> bool:
    """Drop the tail of `items` in place until the state fits. True when anything was dropped."""
    full = list(items)

    def fits_with(k: int) -> bool:
        items[:] = full[:k]
        return _fits(state)

    keep = _largest_fitting_prefix(len(full), fits_with)
    items[:] = full[:keep]
    return keep < len(full)


def _trim_text(state: dict[str, Any], holder: dict[str, Any], key: str) -> bool:
    """Cut the tail of `holder[key]` until the state fits. True when anything was cut."""
    full: str = holder[key]

    def fits_with(k: int) -> bool:
        holder[key] = full[:k]
        return _fits(state)

    keep = _largest_fitting_prefix(len(full), fits_with)
    holder[key] = full[:keep]
    return keep < len(full)


def _trim_post_text(state: dict[str, Any]) -> bool:
    """Last resort once everything else is gone: caption tail, then hashtags, then title tail."""
    post = state["post"]
    truncated = False
    for key in ("caption", "hashtags", "title"):
        if _fits(state):
            break
        if key == "hashtags":
            truncated |= _trim_list(state, post["hashtags"])
        elif key in post:
            truncated |= _trim_text(state, post, key)
            if not post[key]:
                del post[key]
    if not _fits(state):
        # Only the brief and post id remain over the cap; judge it anyway, never skip.
        log.warning(
            "packet.over_cap", post_id=post["id"], tokens=estimate_tokens(state_json(state))
        )
    return truncated


def build_metadata_state(brief: Brief, post: Post) -> dict[str, Any]:
    """Pass-one state: brief, post metadata and the top comments by likes. No evidence."""
    ranked = sorted(post.comments, key=lambda c: c.likes or 0, reverse=True)
    state: dict[str, Any] = {
        "brief": _brief_block(brief),
        "post": _post_block(post),
        "comments": [c.text[:METADATA_COMMENT_CHARS] for c in ranked[:METADATA_COMMENTS]],
    }
    if not _fits(state):
        _trim_list(state, state["comments"])
    if not _fits(state):
        _trim_post_text(state)
    return state


def build_state(brief: Brief, post: Post, evidence: Evidence | None) -> tuple[dict[str, Any], bool]:
    """Pass-two state and whether it was truncated to fit `MAX_STATE_TOKENS`."""
    summary = evidence.comment_summary if evidence else summarize_comments(post.comments, post.lang)
    state: dict[str, Any] = {
        "brief": _brief_block(brief),
        "post": _post_block(post),
        "transcript": [
            {"t": round(s.start_s, 1), "text": s.text}
            for s in (evidence.transcript if evidence else [])
        ],
        "ocr": [
            {"source": o.source.value, "index": o.index, "text": o.text}
            for o in (evidence.ocr if evidence else [])
        ],
        "comments": {
            "count": summary.count,
            "top_terms": list(summary.top_terms),
            "sample": list(summary.sample),
        },
    }
    if _fits(state):
        return state, False

    truncated = False
    # 1. comments: the sample, then the top terms; the count stays
    comments = state["comments"]
    for key in ("sample", "top_terms"):
        if not _fits(state) and comments[key]:
            comments[key] = []
            truncated = True
    # 2. OCR, from the end
    if not _fits(state):
        truncated |= _trim_list(state, state["ocr"])
    # 3. transcript tail; the head is the hook. A lone head segment over budget is cut by chars.
    transcript = state["transcript"]
    if not _fits(state) and transcript:
        head = transcript[0]
        truncated |= _trim_list(state, transcript)
        if not transcript:
            transcript.append(head)
            _trim_text(state, head, "text")
            if not head["text"]:
                transcript.clear()
    # 4. beyond the documented order: the post's own text
    if not _fits(state):
        truncated |= _trim_post_text(state)
    return state, truncated
