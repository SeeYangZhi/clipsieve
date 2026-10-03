import json
import os
from pathlib import Path

import pytest
from structlog.testing import capture_logs

from clipsieve.evidence.asr import FakeASR
from clipsieve.evidence.extract import extract_evidence, resolve_media, run_relative
from clipsieve.evidence.frames import PNG_1X1, FakeFrames
from clipsieve.evidence.ocr import FakeOCR
from clipsieve.models import Evidence, Post
from clipsieve.store.paths import RunPaths, safe_post_filename

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
SNAPSHOTS = FIXTURES / "evidence"


def _load_posts() -> list[Post]:
    return [
        Post.model_validate_json(p.read_text(encoding="utf-8"))
        for p in sorted((FIXTURES / "posts").glob("*.json"))
    ]


def _materialise_media(paths: RunPaths, post: Post) -> Post:
    """Create fake media files plus sidecars so fakes have something to read."""
    dest = paths.media_dir(post.id)
    dest.mkdir(parents=True, exist_ok=True)
    media = []
    for m in post.media:
        if m.type == "video":
            name = "video.mp4"
            (dest / name).write_bytes(b"\x00" * 64)
            (dest / f"{name}.transcript.json").write_text(
                json.dumps(
                    {
                        "lang": post.lang or "en",
                        "segments": [
                            {"start_s": 0.0, "end_s": 2.0, "text": f"hook line for {post.id}"},
                            {"start_s": 2.0, "end_s": 5.0, "text": "second line 第二句"},
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        else:
            name = f"img_{(m.index or 0):02d}.png"
            (dest / name).write_bytes(PNG_1X1)
            (dest / f"{name}.ocr.json").write_text(
                json.dumps([f"overlay {m.index} 房租"], ensure_ascii=False), encoding="utf-8"
            )
        media.append(m.model_copy(update={"local_path": name}))
    # keyframe OCR sidecars for FakeFrames output
    frames_dir = dest / "frames"
    frames_dir.mkdir(exist_ok=True)
    (frames_dir / "hook.jpg.ocr.json").write_text(json.dumps(["STOP SCROLLING"]), encoding="utf-8")
    return post.model_copy(update={"media": media})


@pytest.fixture
def paths(tmp_path: Path) -> RunPaths:
    p = RunPaths(tmp_path / "data", "run-test")
    p.ensure()
    return p


def test_video_post_gets_transcript_frames_and_keyframe_ocr(paths):
    post = next(p for p in _load_posts() if p.kind == "video")
    post = _materialise_media(paths, post)
    ev = extract_evidence(post, paths, FakeASR(), FakeOCR(), FakeFrames(count=2))
    assert ev.post_id == post.id
    assert [s.text for s in ev.transcript][0].startswith("hook line")
    assert ev.keyframes[0] == f"media/{safe_post_filename(post.id)}/frames/hook.jpg"
    assert any(o.source == "keyframe" and o.text == "STOP SCROLLING" for o in ev.ocr)
    assert ev.truncated is False and ev.token_estimate > 0
    assert paths.evidence_json(post.id).is_file()


def test_image_note_gets_ocr_per_image_and_no_transcript(paths):
    post = next(p for p in _load_posts() if p.kind == "image_note")
    post = _materialise_media(paths, post)
    ev = extract_evidence(post, paths, FakeASR(), FakeOCR(), FakeFrames())
    assert ev.transcript == [] and ev.keyframes == []
    assert len([o for o in ev.ocr if o.source == "image"]) == len(post.media)
    assert "房租" in ev.ocr[0].text
    written = paths.evidence_json(post.id).read_text(encoding="utf-8")
    assert "transcript_lang" not in json.loads(written)  # optional means absent
    assert "房租" in written  # real UTF-8, not \u escapes
    assert Evidence.model_validate_json(written) == ev


def test_thumbnail_written_256_wide_for_video_and_image_note(paths):
    from PIL import Image

    video = _materialise_media(paths, next(p for p in _load_posts() if p.kind == "video"))
    extract_evidence(video, paths, FakeASR(), FakeOCR(), FakeFrames(count=2))
    thumb = paths.media_dir(video.id) / "thumb.jpg"
    assert thumb.is_file()
    with Image.open(thumb) as im:
        assert im.width == 256 and im.format == "JPEG"

    note = _materialise_media(paths, next(p for p in _load_posts() if p.kind == "image_note"))
    extract_evidence(note, paths, FakeASR(), FakeOCR(), FakeFrames())
    thumb = paths.media_dir(note.id) / "thumb.jpg"
    assert thumb.is_file()
    with Image.open(thumb) as im:
        assert im.width == 256
    before = thumb.stat().st_mtime_ns
    extract_evidence(note, paths, FakeASR(), FakeOCR(), FakeFrames())
    assert thumb.stat().st_mtime_ns == before  # idempotent


def test_missing_media_file_yields_empty_sections_not_crash(paths):
    post = next(p for p in _load_posts() if p.kind == "video")
    post = post.model_copy(
        update={"media": [m.model_copy(update={"local_path": "video.mp4"}) for m in post.media]}
    )
    ev = extract_evidence(post, paths, FakeASR(), FakeOCR(), FakeFrames())
    assert ev.transcript == [] and ev.ocr == [] and ev.keyframes == []
    assert ev.comment_summary.count == len(post.comments)
    assert not (paths.media_dir(post.id) / "thumb.jpg").exists()


class _CrashingFrames:
    def extract(self, video: Path, dest: Path, max_frames: int = 8) -> list[Path]:
        raise RuntimeError("ffmpeg exploded")


class _GarbageFrames:
    """Writes a keyframe no image library can decode."""

    def extract(self, video: Path, dest: Path, max_frames: int = 8) -> list[Path]:
        dest.mkdir(parents=True, exist_ok=True)
        hook = dest / "hook.jpg"
        hook.write_bytes(b"not an image")
        return [hook]


def test_failing_step_is_logged_and_degrades_without_aborting_the_post(paths):
    videos = [p for p in _load_posts() if p.kind == "video"]
    video = _materialise_media(paths, videos[0])
    media_dir = paths.media_dir(video.id)

    # corrupt transcript and keyframe-OCR sidecars: frames survive, transcript and OCR are empty
    (media_dir / "video.mp4.transcript.json").write_text("{not json", encoding="utf-8")
    (media_dir / "frames" / "hook.jpg.ocr.json").write_text("[broken", encoding="utf-8")
    with capture_logs() as logs:
        ev = extract_evidence(video, paths, FakeASR(), FakeOCR(), FakeFrames(count=2))
    assert ev.transcript == [] and ev.ocr == [] and len(ev.keyframes) == 2
    assert paths.evidence_json(video.id).is_file()
    failed = {(e["event"], e.get("step")) for e in logs if e["log_level"] == "warning"}
    assert {("evidence_step_failed", "asr"), ("evidence_step_failed", "ocr")} <= failed

    # a crashing frame extractor: no keyframes, the transcript is still read
    (media_dir / "video.mp4.transcript.json").write_text(
        json.dumps({"segments": [{"start_s": 0.0, "end_s": 1.0, "text": "still here"}]}),
        encoding="utf-8",
    )
    with capture_logs() as logs:
        ev = extract_evidence(video, paths, FakeASR(), FakeOCR(), _CrashingFrames())
    assert ev.keyframes == [] and [s.text for s in ev.transcript] == ["still here"]
    assert any(e["event"] == "evidence_step_failed" and e["step"] == "frames" for e in logs)

    # an undecodable keyframe: no thumbnail, evidence still produced
    other = _materialise_media(paths, videos[1])
    with capture_logs() as logs:
        ev = extract_evidence(other, paths, FakeASR(), FakeOCR(), _GarbageFrames())
    assert ev.keyframes == [f"media/{safe_post_filename(other.id)}/frames/hook.jpg"]
    assert [p.name for p in paths.media_dir(other.id).glob("thumb*")] == []
    assert any(e["event"] == "thumbnail_failed" for e in logs)

    # one bad image sidecar: the other images are still read
    note = _materialise_media(paths, next(p for p in _load_posts() if p.kind == "image_note"))
    (paths.media_dir(note.id) / "img_01.png.ocr.json").write_text("[broken", encoding="utf-8")
    ev = extract_evidence(note, paths, FakeASR(), FakeOCR(), FakeFrames())
    assert [o.index for o in ev.ocr] == [i for i in range(len(note.media)) if i != 1]


def test_resolve_and_relative_paths(paths):
    post = _load_posts()[0]
    m = post.media[0].model_copy(update={"local_path": "video.mp4"})
    abs_path = resolve_media(paths, post, m)
    assert abs_path == paths.media_dir(post.id) / "video.mp4"
    assert run_relative(paths, abs_path) == f"media/{safe_post_filename(post.id)}/video.mp4"


@pytest.mark.parametrize("post", _load_posts(), ids=lambda p: p.id)
def test_snapshot_matches_fixture(paths, post):
    post = _materialise_media(paths, post)
    ev = extract_evidence(post, paths, FakeASR(), FakeOCR(), FakeFrames(count=2))
    snap = SNAPSHOTS / f"{safe_post_filename(post.id)}.json"
    rendered = (
        json.dumps(
            ev.model_dump(mode="json", by_alias=True, exclude_none=True),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    if os.environ.get("UPDATE_SNAPSHOTS") == "1" or not snap.exists():
        SNAPSHOTS.mkdir(parents=True, exist_ok=True)
        snap.write_text(rendered, encoding="utf-8")
    # Compared as parsed objects, not bytes: committed snapshots are Biome-formatted
    # (`bunx ultracite fix` after regenerating collapses short arrays).
    assert Evidence.model_validate_json(snap.read_text(encoding="utf-8")) == ev
