from pathlib import Path

from clipsieve.adapters.vtt import parse_vtt, vtt_lang_from_filename

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "youtube"


def test_parse_vtt_rolling_cues():
    segments = parse_vtt((FIXTURES / "aB3dEfGhIjK.en.vtt").read_text(encoding="utf-8"))
    texts = [s.text for s in segments]
    assert texts == [
        "stop scrolling I built a Chrome extension",
        "in 10 minutes with zero code",
        "here's exactly how",
    ]
    starts = [s.start_s for s in segments]
    assert starts == sorted(starts)
    assert all(s.end_s > s.start_s for s in segments)
    assert segments[0].start_s == 0.0 and segments[0].end_s == 2.5


def test_parse_vtt_strips_inline_tags_and_positions():
    raw = (
        "WEBVTT\n\n00:00:01.000 --> 00:00:02.000 align:start position:0%\n"
        "hello<00:00:01.500><c> world</c>\n"
    )
    [seg] = parse_vtt(raw)
    assert seg.text == "hello world"


def test_parse_vtt_decodes_character_references():
    # YouTube marks speaker changes with &gt;&gt;. Decode after tag stripping, so an escaped
    # tag stays literal text and &nbsp; collapses into a plain space.
    raw = (
        "WEBVTT\n\n00:00:01.000 --> 00:00:03.000 align:start position:0%\n"
        "&gt;&gt;<00:00:01.200><c> Tom</c><00:00:01.500><c> &amp;</c><c> Jerry</c>\n"
        "\n00:00:03.000 --> 00:00:04.000\n"
        "at 5&nbsp;pm &lt;b&gt;sharp&lt;/b&gt;\n"
    )
    first, second = parse_vtt(raw)
    assert first.text == ">> Tom & Jerry"
    assert second.text == "at 5 pm <b>sharp</b>"


def test_parse_vtt_chinese():
    segments = parse_vtt((FIXTURES / "zH1sH4nGh41.zh-Hans.vtt").read_text(encoding="utf-8"))
    assert segments[0].text == "刚到上海的第一天 房租真的好贵"


def test_vtt_lang_from_filename():
    assert vtt_lang_from_filename(Path("video.en.vtt")) == "en"
    assert vtt_lang_from_filename(Path("video.zh-Hans.vtt")) == "zh-Hans"
    assert vtt_lang_from_filename(Path("video.vtt")) is None
