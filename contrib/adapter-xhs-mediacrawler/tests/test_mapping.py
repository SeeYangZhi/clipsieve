import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from clipsieve.adapters.base import hash_creator
from clipsieve.models import Post

from clipsieve_xhs import mapping
from clipsieve_xhs.mapping import group_comments, map_note, parse_count, split_list

FIX = Path(__file__).parent / "fixtures" / "mediacrawler-output"
SALT = "test-salt"
NOW = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)


@pytest.fixture
def notes() -> list[dict]:
    return json.loads((FIX / "notes.json").read_text(encoding="utf-8"))


@pytest.fixture
def comments() -> dict[str, list[dict]]:
    return group_comments(json.loads((FIX / "comments.json").read_text(encoding="utf-8")))


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1.2万", 12000),
        ("3,210", 3210),
        (15, 15),
        ("", None),
        (None, None),
        ("0", 0),
        ("2.5w", 25000),
        ("abc", None),
    ],
)
def test_parse_count(raw, expected):
    assert parse_count(raw) == expected


def test_split_list_handles_empty_and_delimiter():
    assert split_list("") == []
    assert split_list(None) == []
    assert split_list("a,b, c") == ["a", "b", "c"]
    assert split_list(["x", "y"]) == ["x", "y"]


def test_group_comments_keeps_only_top_level_sorted_by_likes(comments):
    top = comments["66f1a2b3c4d5e6f700000001"]
    assert [c["comment_id"] for c in top] == ["c004", "c001", "c002"]  # c003 is a reply, excluded


def test_video_note_maps_every_field(notes, comments):
    n = notes[0]
    post = map_note(
        n,
        comments[n["note_id"]],
        SALT,
        raw_ref="raw/xiaohongshu__66f1a2b3c4d5e6f700000001.json",
        collected_at=NOW,
    )
    assert isinstance(post, Post)
    assert post.id == "xiaohongshu:66f1a2b3c4d5e6f700000001"
    assert post.platform.value == "xiaohongshu"
    assert post.url == "https://www.xiaohongshu.com/explore/66f1a2b3c4d5e6f700000001"
    assert post.kind.value == "video"
    assert post.creator_hash == hash_creator("mc_7c1f4a9e2b", SALT)
    assert post.creator_display == "小*"
    assert post.posted_at == datetime.fromtimestamp(1758240000, tz=UTC)
    assert post.text.title == "新加坡人搬来上海的第一周｜真实记录 🇸🇬➡️🇨🇳"
    assert post.text.hashtags == ["新加坡人在上海", "上海生活", "vlog日常"]
    assert len(post.media) == 1 and post.media[0].type.value == "video"
    assert post.media[0].local_path is None
    assert post.metrics.likes == 12000 and post.metrics.saves == 3456
    assert (
        post.metrics.comments == 289 and post.metrics.shares == 120 and post.metrics.views is None
    )
    assert [c.text for c in post.comments] == [
        "地铁迷路那段笑死，我第一次也是坐反方向",
        "外卖速度真的离谱哈哈哈，欢迎来上海！",
        "同新加坡人，刚到上海一个月，求租房攻略🙏",
    ]
    assert post.comments[0].likes == 415
    assert post.lang == "zh"
    assert post.raw_ref == "raw/xiaohongshu__66f1a2b3c4d5e6f700000001.json"
    assert post.collected_at == NOW


def test_image_note_has_one_media_per_image_with_index(notes, comments):
    n = notes[1]
    post = map_note(n, comments[n["note_id"]], SALT, raw_ref="r", collected_at=NOW)
    assert post.kind.value == "image_note"
    assert [m.index for m in post.media] == [0, 1, 2]
    assert all(m.type.value == "image" for m in post.media)
    assert post.metrics.saves == 2310


def test_normal_note_without_images(notes):
    n = notes[2]
    post = map_note(n, [], SALT, raw_ref="r", collected_at=NOW)
    assert post.kind.value == "image_note" and post.media == []
    assert post.metrics.likes is None and post.metrics.comments == 0
    assert post.text.hashtags == [] and post.comments == []


def test_mapping_preserves_cjk_exactly(notes, comments):
    n = notes[0]
    post = map_note(n, comments[n["note_id"]], SALT, raw_ref="r", collected_at=NOW)
    dumped = post.model_dump_json()
    for s in (n["title"], n["desc"], "外卖速度真的离谱哈哈哈，欢迎来上海！", "🇸🇬➡️🇨🇳", "｜"):
        assert s in dumped
    rt = Post.model_validate_json(dumped)
    assert rt.text.title == n["title"] and rt.text.caption == n["desc"]


def test_comments_capped_at_50():
    many = [
        {
            "comment_id": f"c{i}",
            "note_id": "n",
            "content": f"评论{i}",
            "like_count": str(i),
            "parent_comment_id": "0",
        }
        for i in range(80)
    ]
    post = map_note(
        {
            "note_id": "n",
            "type": "normal",
            "title": "",
            "desc": "",
            "note_url": "https://www.xiaohongshu.com/explore/n",
            "creator_hash": "x",
        },
        group_comments(many)["n"],
        SALT,
        raw_ref="r",
        collected_at=NOW,
    )
    assert len(post.comments) == 50 and post.comments[0].text == "评论79"


def test_field_map_is_overridable(monkeypatch, notes):
    monkeypatch.setitem(mapping.FIELD_MAP, "caption", "title")
    post = map_note(notes[2], [], SALT, raw_ref="r", collected_at=NOW)
    assert post.text.caption == notes[2]["title"]
