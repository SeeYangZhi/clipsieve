from clipsieve.evidence.comments import is_cjk, summarize_comments, tokenize
from clipsieve.models import Comment


def test_english_top_terms_exclude_stopwords():
    comments = [
        Comment(text="this hook is the best hook ever", likes=10),
        Comment(text="the hook works, great hook", likes=5),
        Comment(text="saved it", likes=1),
    ]
    s = summarize_comments(comments, "en")
    assert s.count == 3
    assert s.top_terms[0] == "hook"
    assert "the" not in s.top_terms and "is" not in s.top_terms


def test_samples_are_top_five_by_likes():
    comments = [Comment(text=f"c{i}", likes=i) for i in range(8)] + [
        Comment(text="nolikes", likes=None)
    ]
    s = summarize_comments(comments, "en")
    assert s.sample == ["c7", "c6", "c5", "c4", "c3"]


def test_chinese_bigrams_and_stop_chars():
    comments = [
        Comment(text="房租好贵，房租真的贵", likes=3),
        Comment(text="上海房租太贵了", likes=9),
        Comment(text="我也是新加坡人", likes=2),
    ]
    s = summarize_comments(comments, "zh")
    assert "房租" in s.top_terms[:2]
    assert all("的" not in t and "了" not in t for t in s.top_terms)
    assert s.sample[0] == "上海房租太贵了"


def test_cjk_detection_and_tokenize():
    assert is_cjk("房租好贵") and not is_cjk("rent is high")
    assert tokenize("Stop scrolling, I built it!", "en") == [
        "stop",
        "scrolling",
        "i",
        "built",
        "it",
    ]
    assert tokenize("房租好贵", "zh") == ["房租", "租好", "好贵"]


def test_empty_comments():
    s = summarize_comments([], None)
    assert s.count == 0 and s.top_terms == [] and s.sample == []


def test_mixed_language_auto_detects_cjk_when_lang_missing():
    s = summarize_comments(
        [Comment(text="上海房租", likes=1), Comment(text="上海生活", likes=1)], None
    )
    assert "上海" in s.top_terms
