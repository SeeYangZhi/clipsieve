"""Turn one post's downloaded media into `Evidence`: transcript, OCR, keyframes, comment summary.

Per-post robustness: a missing file, a failing ASR/OCR/frame step or a corrupt sidecar is logged
and leaves that section empty; the post still gets evidence. `truncated` is always False here;
the Runner sets it from `build_state` (Addendum B.3).
"""

from __future__ import annotations

import contextlib
from pathlib import Path

from clipsieve.evidence.asr import ASR
from clipsieve.evidence.comments import summarize_comments
from clipsieve.evidence.frames import FrameExtractor
from clipsieve.evidence.ocr import OCR, ocr_lang_for_post
from clipsieve.evidence.packet import estimate_tokens
from clipsieve.logging import get_logger
from clipsieve.models import Evidence, Media, OcrItem, Post, TranscriptSegment
from clipsieve.store.paths import RunPaths

log = get_logger(__name__)

MAX_KEYFRAMES = 8
THUMB_WIDTH = 256
THUMB_NAME = "thumb.jpg"


def write_thumbnail(paths: RunPaths, post: Post, source: Path | None) -> Path | None:
    """Write media_dir/thumb.jpg, 256px wide, from the first keyframe or first image.

    Idempotent: an existing thumbnail is kept. Written via a temp file so a failed save never
    leaves a partial thumbnail behind. Failures are logged and return None; never fatal.
    """
    if source is None or not source.exists():
        return None
    target = paths.media_dir(post.id) / THUMB_NAME
    if target.exists():
        return target
    tmp = target.with_name(THUMB_NAME + ".tmp")
    try:
        from PIL import Image

        target.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(source) as im:
            rgb = im.convert("RGB")
        height = max(1, round(rgb.height * THUMB_WIDTH / max(1, rgb.width)))
        rgb.resize((THUMB_WIDTH, height)).save(tmp, format="JPEG", quality=85)
        tmp.replace(target)
    except Exception as exc:  # a bad frame must not fail extraction
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)
        log.warning("thumbnail_failed", post_id=post.id, source=str(source), error=repr(exc))
        return None
    return target


def resolve_media(paths: RunPaths, post: Post, media: Media) -> Path:
    """`Media.local_path` is relative to the post's media dir (Addendum B.2)."""
    if media.local_path is None:
        raise FileNotFoundError(f"media for {post.id} has no local_path")
    return paths.media_dir(post.id) / media.local_path


def run_relative(paths: RunPaths, path: Path) -> str:
    return path.resolve().relative_to(paths.root.resolve()).as_posix()


def _step_failed(post: Post, step: str, media: Path, exc: Exception) -> None:
    log.warning(
        "evidence_step_failed",
        post_id=post.id,
        step=step,
        media=str(media),
        error_type=type(exc).__name__,
        error=str(exc),
    )


def _ocr_text(post: Post, ocr: OCR, image: Path, lang: str) -> str:
    try:
        return " ".join(ocr.read(image, lang)).strip()
    except Exception as exc:
        _step_failed(post, "ocr", image, exc)
        return ""


def _write_evidence(path: Path, evidence: Evidence) -> None:
    """Optional means absent; written via a temp file like the store's run files."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        evidence.model_dump_json(indent=2, by_alias=True, exclude_none=True), encoding="utf-8"
    )
    tmp.replace(path)


def extract_evidence(
    post: Post, paths: RunPaths, asr: ASR, ocr: OCR, frames: FrameExtractor
) -> Evidence:
    ocr_lang = ocr_lang_for_post(post.lang)
    transcript: list[TranscriptSegment] = []
    transcript_lang: str | None = None
    ocr_items: list[OcrItem] = []
    keyframes: list[str] = []

    for media in post.media:
        if media.local_path is None:
            log.warning("evidence_media_missing_path", post_id=post.id)
            continue
        path = resolve_media(paths, post, media)
        if not path.exists():
            log.warning("evidence_media_missing_file", post_id=post.id, path=str(path))
            continue

        if media.type == "video":
            try:
                frame_paths = frames.extract(
                    path, paths.media_dir(post.id) / "frames", max_frames=MAX_KEYFRAMES
                )
            except Exception as exc:
                _step_failed(post, "frames", path, exc)
                frame_paths = []
            for i, frame in enumerate(frame_paths[:MAX_KEYFRAMES]):
                keyframes.append(run_relative(paths, frame))
                text = _ocr_text(post, ocr, frame, ocr_lang)
                if text:
                    ocr_items.append(OcrItem(source="keyframe", index=i, text=text))
            try:
                segments, lang = asr.transcribe(path, post.lang or None)
            except Exception as exc:
                _step_failed(post, "asr", path, exc)
                segments, lang = [], None
            transcript.extend(segments)
            transcript_lang = transcript_lang or lang
        else:
            text = _ocr_text(post, ocr, path, ocr_lang)
            if text:
                ocr_items.append(OcrItem(source="image", index=media.index or 0, text=text))

    thumb_source: Path | None = None
    if keyframes:
        thumb_source = paths.root / keyframes[0]
    else:
        first_image = next((m for m in post.media if m.type == "image" and m.local_path), None)
        if first_image is not None:
            thumb_source = resolve_media(paths, post, first_image)
    write_thumbnail(paths, post, thumb_source)

    comment_summary = summarize_comments(list(post.comments), post.lang)
    # The estimate covers transcript, OCR and comment-summary text only (Addendum B.3).
    text_blob = " ".join(
        [s.text for s in transcript]
        + [o.text for o in ocr_items]
        + comment_summary.sample
        + comment_summary.top_terms
    )
    evidence = Evidence(
        post_id=post.id,
        transcript=transcript,
        transcript_lang=transcript_lang,
        ocr=ocr_items,
        keyframes=keyframes[:MAX_KEYFRAMES],
        comment_summary=comment_summary,
        token_estimate=estimate_tokens(text_blob),
        truncated=False,
    )
    _write_evidence(paths.evidence_json(post.id), evidence)
    log.info(
        "evidence_extracted",
        post_id=post.id,
        segments=len(transcript),
        ocr=len(ocr_items),
        keyframes=len(keyframes),
    )
    return evidence
