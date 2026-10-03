from datetime import UTC, datetime
from typing import Any

from structlog.testing import capture_logs

from clipsieve.evidence.packet import (
    MAX_STATE_TOKENS,
    build_metadata_state,
    build_state,
    estimate_tokens,
    state_json,
)
from clipsieve.models import (
    Brief,
    Comment,
    CommentSummary,
    Evidence,
    Media,
    Metrics,
    OcrItem,
    Post,
    PostText,
    TranscriptSegment,
)


def _brief() -> Brief:
    return Brief(
        text="Singaporean moving to Shanghai, vlog style",
        topic="Shanghai expat life",
        audience="Singaporeans in China",
        persona="Singaporean vlogger new to Shanghai",
    )


def _post(lang: str = "en") -> Post:
    return Post(
        id="youtube:abc",
        platform="youtube",
        url="https://www.youtube.com/shorts/abc",
        creator_hash="0" * 64,
        creator_display="Nat",
        posted_at=datetime(2026, 9, 1, tzinfo=UTC),
        kind="video",
        text=PostText(title="Day one", caption="房租好贵 #上海", hashtags=["上海"]),
        media=[Media(type="video", duration_s=50)],
        metrics=Metrics(views=1000, likes=100, comments=10),
        comments=[Comment(text="真实", likes=5), Comment(text="great", likes=2)],
        lang=lang,
        raw_ref="raw/x.json",
        collected_at=datetime(2026, 10, 3, tzinfo=UTC),
    )


def _evidence(transcript_chars: int = 100, ocr_items: int = 2, zh: bool = False) -> Evidence:
    word = "房" if zh else "word "
    seg_text = word * (40 if zh else 8)
    n = max(1, transcript_chars // len(seg_text))
    return Evidence(
        post_id="youtube:abc",
        transcript=[
            TranscriptSegment(start_s=i * 2.0, end_s=i * 2.0 + 2.0, text=seg_text) for i in range(n)
        ],
        transcript_lang="zh" if zh else "en",
        ocr=[OcrItem(source="keyframe", index=i, text=f"ocr {i}") for i in range(ocr_items)],
        keyframes=["media/youtube__abc/frames/hook.jpg"],
        comment_summary=CommentSummary(
            count=2, top_terms=["真实", "great"], sample=["真实", "great"]
        ),
        token_estimate=0,
        truncated=False,
    )


def test_estimate_tokens_counts_cjk_per_char():
    assert estimate_tokens("abcdef") == 2
    assert estimate_tokens("房租好贵") == 4
    assert estimate_tokens("房租 rent") == 2 + len(" rent") // 3


def test_metadata_state_has_no_transcript_or_ocr():
    state = build_metadata_state(_brief(), _post())
    assert set(state) == {"brief", "post", "comments"}
    assert state["post"]["caption"] == "房租好贵 #上海"
    assert state["comments"] == ["真实", "great"]


def test_state_under_cap_untouched():
    state, truncated = build_state(_brief(), _post(), _evidence())
    assert truncated is False
    assert set(state) == {"brief", "post", "transcript", "ocr", "comments"}
    assert len(state["transcript"]) == 2 and len(state["ocr"]) == 2
    assert state["comments"]["sample"] == ["真实", "great"]


def test_state_without_evidence_has_empty_sections():
    state, truncated = build_state(_brief(), _post(), None)
    assert state["transcript"] == [] and state["ocr"] == [] and truncated is False


def test_truncation_order_comments_then_ocr_then_transcript():
    ev = _evidence(transcript_chars=MAX_STATE_TOKENS * 3 + 3000, ocr_items=5)
    state, truncated = build_state(_brief(), _post(), ev)
    assert truncated is True
    assert state["comments"]["sample"] == [] and state["comments"]["top_terms"] == []
    assert state["ocr"] == []
    assert 0 < len(state["transcript"]) < len(ev.transcript)
    assert state["transcript"][0]["text"] == ev.transcript[0].text  # head kept, tail dropped
    assert estimate_tokens(state_json(state)) <= MAX_STATE_TOKENS


def test_partial_truncation_stops_as_soon_as_it_fits():
    # A 40-char segment costs ~62 chars of JSON: 45,000 transcript chars is ~24k tokens.
    ev = _evidence(transcript_chars=45_000, ocr_items=400)
    without_ocr, _ = build_state(_brief(), _post(), ev.model_copy(update={"ocr": []}))
    assert estimate_tokens(state_json(without_ocr)) <= MAX_STATE_TOKENS  # precondition
    state, truncated = build_state(_brief(), _post(), ev)
    assert truncated is True
    assert state["comments"]["sample"] == []
    assert len(state["transcript"]) == len(
        ev.transcript
    )  # transcript untouched: ocr trimming was enough
    assert 0 < len(state["ocr"]) < len(ev.ocr)  # ocr trimmed from the end, not wiped
    assert state["ocr"][0]["text"] == "ocr 0"
    assert estimate_tokens(state_json(state)) <= MAX_STATE_TOKENS


def test_cjk_estimate_and_truncation():
    ev = _evidence(transcript_chars=15_000, zh=True)
    joined = "".join(s.text for s in ev.transcript)
    assert estimate_tokens(joined) >= 14_000
    ev_big = _evidence(transcript_chars=40_000, zh=True)
    state, truncated = build_state(_brief(), _post("zh"), ev_big)
    assert truncated is True
    assert estimate_tokens(state_json(state)) <= MAX_STATE_TOKENS
    assert state["post"]["caption"] == "房租好贵 #上海"


def test_state_json_is_deterministic_and_unicode():
    state, _ = build_state(_brief(), _post(), _evidence())
    a, b = state_json(state), state_json(state)
    assert a == b and "房租好贵" in a and "\\u" not in a


def test_estimate_tokens_counts_cjk_punctuation_kana_and_hangul():
    assert estimate_tokens("，。！") == 3
    assert estimate_tokens("ひらがなカタカナ") == 8
    assert estimate_tokens("한국어") == 3


def _assert_plain(value: Any) -> None:
    """Jev state holds only str, int, float, list and dict: no None, bool or enum members."""
    if type(value) is dict:
        for k, v in value.items():
            assert type(k) is str
            _assert_plain(v)
    elif type(value) is list:
        for v in value:
            _assert_plain(v)
    else:
        assert type(value) in (str, int, float), f"{value!r} is {type(value).__name__}"


def test_states_hold_only_plain_json_values():
    sparse = _post().model_copy(
        update={
            "posted_at": None,
            "lang": None,
            "text": PostText(title=None, caption="cap", hashtags=[]),
            "media": [Media(type="image")],
            "metrics": Metrics(views=10),
        }
    )
    meta = build_metadata_state(_brief(), sparse)
    full, _ = build_state(_brief(), sparse, _evidence())
    for state in (meta, full, build_state(_brief(), _post(), _evidence())[0]):
        _assert_plain(state)
    assert not {"posted_at", "lang", "title", "duration_s"} & set(full["post"])  # absent, not null
    assert full["post"]["platform"] == "youtube" and full["ocr"][0]["source"] == "keyframe"


def test_state_without_evidence_summarises_post_comments():
    post = _post().model_copy(
        update={"comments": [Comment(text="meh", likes=1), Comment(text="love the hook", likes=9)]}
    )
    state, truncated = build_state(_brief(), post, None)
    assert truncated is False
    assert state["comments"]["count"] == 2
    assert state["comments"]["sample"] == ["love the hook", "meh"]  # ranked by likes


def test_single_oversized_cjk_segment_is_cut_to_fit():
    ev = _evidence(zh=True).model_copy(
        update={"transcript": [TranscriptSegment(start_s=0.0, end_s=900.0, text="房" * 60_000)]}
    )
    state, truncated = build_state(_brief(), _post("zh"), ev)
    assert truncated is True
    assert state["ocr"] == []
    assert len(state["transcript"]) == 1
    kept = state["transcript"][0]["text"]
    assert 20_000 < len(kept) < 60_000 and ev.transcript[0].text.startswith(kept)
    assert estimate_tokens(state_json(state)) <= MAX_STATE_TOKENS


def test_post_text_over_cap_still_yields_a_judgeable_state():
    huge = _post("zh").model_copy(
        update={"text": PostText(title="Day one", caption="贵" * 100_000, hashtags=["上海"])}
    )
    state, truncated = build_state(_brief(), huge, _evidence(transcript_chars=2_000, ocr_items=3))
    assert truncated is True
    assert estimate_tokens(state_json(state)) <= MAX_STATE_TOKENS
    assert state["brief"]["text"] == _brief().text
    assert state["post"]["id"] == "youtube:abc" and state["post"]["title"] == "Day one"
    assert 20_000 < len(state["post"]["caption"]) < 100_000  # caption head kept
    # the documented order ran first: comments, ocr and transcript all gave way before the caption
    assert state["comments"]["sample"] == [] and state["ocr"] == [] and state["transcript"] == []
    meta = build_metadata_state(_brief(), huge)
    assert estimate_tokens(state_json(meta)) <= MAX_STATE_TOKENS
    assert meta["comments"] == [] and 20_000 < len(meta["post"]["caption"]) < 100_000


def test_over_cap_brief_is_still_returned_for_judging():
    brief = _brief().model_copy(update={"text": "贵" * 30_000})
    with capture_logs() as logs:
        state, truncated = build_state(brief, _post("zh"), _evidence(transcript_chars=2_000))
    assert truncated is True
    assert state["transcript"] == [] and state["ocr"] == [] and state["post"]["hashtags"] == []
    assert "caption" not in state["post"] and "title" not in state["post"]
    assert state["post"]["id"] == "youtube:abc" and state["brief"]["text"] == brief.text
    assert [e["event"] for e in logs] == ["packet.over_cap"]
