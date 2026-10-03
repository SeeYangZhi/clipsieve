import math
from pathlib import Path

from clipsieve.judge.rubric import load_pack
from clipsieve.models import JudgeAnswer, JudgeResult
from clipsieve.select.quotas import violates_quota
from clipsieve.select.select import Selection, pass_one_keep, select

RUBRICS = Path(__file__).resolve().parents[3] / "rubrics"
# Default labels vary by post_id so quotas only bite where a test asks for it.
FORMATS = ["vlog_montage", "talking_head", "screen_demo", "meme", "image_carousel"]
HOOK_TYPES = ["story", "curiosity_gap", "question", "list", "other"]
LEG = {str(i): f"L{i}" for i in range(5)}


def _label_index(post_id):
    return sum(ord(c) for c in post_id)


def sc(v, conf=0.9):
    return JudgeAnswer(type="score", value=v, confidence=conf, probabilities={}, legend=LEG)


def ch(v, conf=0.9):
    return JudgeAnswer(type="choice", value=v, confidence=conf, probabilities={v: conf})


def nl(p):
    return JudgeAnswer(type="noul", value=p)


def r(
    post_id,
    hook=3.0,
    persona=3.0,
    niche=3.0,
    fmt=None,
    hook_type=None,
    risky=0.1,
    conf=0.9,
    pass_name="pass_two",
):
    fmt = fmt or FORMATS[_label_index(post_id) % len(FORMATS)]
    hook_type = hook_type or HOOK_TYPES[_label_index(post_id) % len(HOOK_TYPES)]
    answers = {
        "hook_strength": sc(hook, conf),
        "persona_fit": sc(persona, conf),
        "niche_relevance": sc(niche, conf),
        "format": ch(fmt, conf),
        "hook_type": ch(hook_type, conf),
        "risky_claim": nl(risky),
        "format_guess": ch("unknown", conf),
    }
    return JudgeResult(
        post_id=post_id,
        pass_name=pass_name,
        model="jev",
        input_tokens=1,
        latency_ms=1,
        answers=answers,
    )


def small_pack(shortlist_size=5):
    pack = load_pack(RUBRICS / "creator-hooks-v1.yaml")
    return pack.model_copy(
        update={"selection": pack.selection.model_copy(update={"shortlist_size": shortlist_size})},
        deep=True,
    )


def test_violates_quota_counts_same_label_against_max_share():
    pack = small_pack(5)  # format max_share 0.4 -> at most 2 of 5 may share a format
    chosen = [r("a", fmt="talking_head"), r("b", fmt="talking_head")]
    assert violates_quota(r("c", fmt="talking_head"), chosen, pack, 5) is True
    assert violates_quota(r("d", fmt="vlog_montage"), chosen, pack, 5) is False
    # candidate missing the diversity question is never blocked by it
    cand = r("e", fmt="talking_head")
    del cand.answers["format"]
    assert violates_quota(cand, chosen, pack, 5) is False


def test_select_orders_by_composite_routes_review_and_filters():
    pack = small_pack(3)
    results = [
        r("low", hook=1, persona=1, niche=1),
        r("high", hook=4, persona=4, niche=4),
        r("mid", hook=2, persona=3, niche=3),
        r("risky", hook=4, persona=4, niche=4, risky=0.9),
        r("unsure", hook=4, persona=4, niche=4, conf=0.3),
    ]
    sel = select(results, pack)
    assert isinstance(sel, Selection)
    assert sel.shortlist == ["high", "mid", "low"]
    assert sel.review == ["unsure"]
    assert sel.dropped == {"risky": "hard_filter"}
    assert sel.scores["high"] > sel.scores["mid"] > sel.scores["low"]
    assert "unsure" in sel.scores and "risky" in sel.scores


def test_select_applies_quota_and_marks_overflow():
    pack = small_pack(2)  # hook_type max_share 0.5 -> 1 per hook type among 2
    results = [
        r("s1", hook=4, hook_type="story", fmt="vlog_montage"),
        r("s2", hook=3.5, hook_type="story", fmt="talking_head"),
        r("c1", hook=3, hook_type="curiosity_gap", fmt="screen_demo"),
        r("c2", hook=2, hook_type="curiosity_gap", fmt="meme"),
    ]
    sel = select(results, pack)
    assert sel.shortlist == ["s1", "c1"]
    assert sel.dropped["s2"] == "quota"
    assert sel.dropped["c2"] == "not_selected"


def test_select_is_deterministic_on_ties():
    pack = small_pack(2)
    results = [r("b"), r("a"), r("c")]
    assert select(results, pack).shortlist == ["a", "b"]


def test_select_with_weights_override_changes_order_without_judge():
    pack = small_pack(1)
    results = [r("hooky", hook=4, persona=0), r("fits", hook=0, persona=4)]
    assert select(results, pack).shortlist == [
        "fits"
    ]  # equal composite on default weights; tie broken by post_id
    assert select(results, pack, weights_override={"hook_strength": 1.0}).shortlist == ["hooky"]


def test_pass_one_keep_keeps_top_fraction_min_one():
    pack = load_pack(RUBRICS / "creator-hooks-v1.yaml")  # pass_one_keep 0.30
    results = [
        JudgeResult(
            post_id=f"p{i}",
            pass_name="pass_one",
            model="jev",
            input_tokens=1,
            latency_ms=1,
            answers={"niche_relevance": sc(float(i % 5)), "format_guess": ch("unknown")},
        )
        for i in range(10)
    ]
    kept = pass_one_keep(results, pack)
    assert len(kept) == math.ceil(0.30 * 10) == 3
    assert kept == {"p3", "p4", "p9"}  # scores 4,4 then the 3s; tie among p3/p8 broken by post_id
    assert pass_one_keep(results[:1], pack) == {"p0"}
    assert pass_one_keep([], pack) == set()
