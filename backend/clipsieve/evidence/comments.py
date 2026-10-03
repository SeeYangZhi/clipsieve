from __future__ import annotations

import re
from collections import Counter

from clipsieve.models import Comment, CommentSummary

TOP_TERMS = 10
SAMPLES = 5

_EN_STOP = set(
    """
    a an the and or but is are was were be been it its this that these those i you he she we
    they me my your of to in on for with at by from as so if then than too very just not no
    yes do does did have has had what which who how why when where there here all any can
    will would should could ever also about up out
    """.split()
)
_ZH_STOP_CHARS = set(
    "的了是我你他她它们在和就不都也这那有人吗呢吧啊呀哦嗯很太还又把被让给对去来说看到"
)

_CJK = re.compile(r"[一-鿿]")
_EN_WORD = re.compile(r"[a-zA-Z']+")
_CJK_RUN = re.compile(r"[一-鿿]+")


def is_cjk(text: str) -> bool:
    cjk = len(_CJK.findall(text))
    letters = len(_EN_WORD.findall(text))
    return cjk > 0 and cjk >= letters


def _use_cjk(text: str, lang: str | None) -> bool:
    return (lang or "").lower().startswith("zh") or (lang is None and is_cjk(text))


def tokenize(text: str, lang: str | None) -> list[str]:
    if _use_cjk(text, lang):
        tokens: list[str] = []
        for run in _CJK_RUN.findall(text):
            tokens.extend(run[i : i + 2] for i in range(len(run) - 1))
        return tokens
    return [w.lower().strip("'") for w in _EN_WORD.findall(text) if w.strip("'")]


def _is_stop(token: str, cjk: bool) -> bool:
    if cjk:
        return any(c in _ZH_STOP_CHARS for c in token)
    return token in _EN_STOP or len(token) < 2


def summarize_comments(comments: list[Comment], lang: str | None) -> CommentSummary:
    if not comments:
        return CommentSummary(count=0, top_terms=[], sample=[])
    joined = " ".join(c.text for c in comments)
    cjk = _use_cjk(joined, lang)
    counter: Counter[str] = Counter()
    for c in comments:
        for tok in tokenize(c.text, "zh" if cjk else "en"):
            if not _is_stop(tok, cjk):
                counter[tok] += 1
    top_terms = [t for t, _ in counter.most_common(TOP_TERMS)]
    ranked = sorted(comments, key=lambda c: c.likes or 0, reverse=True)
    sample = [c.text for c in ranked[:SAMPLES]]
    return CommentSummary(count=len(comments), top_terms=top_terms, sample=sample)
