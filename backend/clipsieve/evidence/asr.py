from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from clipsieve.logging import get_logger
from clipsieve.models import TranscriptSegment

log = get_logger(__name__)

MLX_REPO = "mlx-community/whisper-large-v3-mlx"

# Whisper's language codes (large-v3, including `yue`). mlx-whisper and faster-whisper raise
# ValueError for anything else, such as `zh-Hans` or `en-US`.
WHISPER_LANGUAGES = frozenset(
    {
        "af", "am", "ar", "as", "az", "ba", "be", "bg", "bn", "bo", "br", "bs", "ca", "cs",
        "cy", "da", "de", "el", "en", "es", "et", "eu", "fa", "fi", "fo", "fr", "gl", "gu",
        "ha", "haw", "he", "hi", "hr", "ht", "hu", "hy", "id", "is", "it", "ja", "jw", "ka",
        "kk", "km", "kn", "ko", "la", "lb", "ln", "lo", "lt", "lv", "mg", "mi", "mk", "ml",
        "mn", "mr", "ms", "mt", "my", "ne", "nl", "nn", "no", "oc", "pa", "pl", "ps", "pt",
        "ro", "ru", "sa", "sd", "si", "sk", "sl", "sn", "so", "sq", "sr", "su", "sv", "sw",
        "ta", "te", "tg", "th", "tk", "tl", "tr", "tt", "uk", "ur", "uz", "vi", "yi", "yo",
        "yue", "zh",
    }
)  # fmt: skip
# Primary subtags whose Whisper code differs (legacy ISO 639 codes, BCP 47 variants).
_LANG_ALIASES = {"iw": "he", "in": "id", "ji": "yi", "jv": "jw", "nb": "no", "fil": "tl"}


def normalize_lang_hint(hint: str | None) -> str | None:
    """`zh-Hans` -> `zh`, `en-US` -> `en`. None (auto-detect) when Whisper has no such language."""
    primary = (hint or "").replace("_", "-").split("-")[0].strip().lower()
    primary = _LANG_ALIASES.get(primary, primary)
    return primary if primary in WHISPER_LANGUAGES else None


def read_sidecar_transcript(media: Path) -> tuple[list[TranscriptSegment], str | None] | None:
    """Read `<media>.transcript.json`. None when absent; the `lang` key may be missing."""
    sidecar = media.with_name(media.name + ".transcript.json")
    if not sidecar.exists():
        return None
    data = json.loads(sidecar.read_text(encoding="utf-8"))
    segments = [TranscriptSegment.model_validate(s) for s in data.get("segments", [])]
    return segments, data.get("lang") or None


@runtime_checkable
class ASR(Protocol):
    def transcribe(
        self, media: Path, lang_hint: str | None
    ) -> tuple[list[TranscriptSegment], str | None]: ...


class FakeASR:
    """Returns the caption sidecar when present, else nothing."""

    def transcribe(
        self, media: Path, lang_hint: str | None
    ) -> tuple[list[TranscriptSegment], str | None]:
        sidecar = read_sidecar_transcript(media)
        return sidecar if sidecar is not None else ([], None)


class WhisperASR:
    """mlx-whisper on Apple Silicon when importable, faster-whisper otherwise.

    Heavy imports happen inside methods. A caption sidecar short-circuits transcription.
    One instance is shared by concurrent extractions, so model construction and inference run
    under a per-instance lock; sidecar reads do not take it.
    """

    def __init__(self, model_name: str = "large-v3") -> None:
        self._model_name = model_name
        self._faster_model: Any = None
        self._lock = threading.Lock()

    def transcribe(
        self, media: Path, lang_hint: str | None
    ) -> tuple[list[TranscriptSegment], str | None]:
        sidecar = read_sidecar_transcript(media)
        if sidecar is not None:
            log.info("asr.sidecar_used", media=str(media))
            return sidecar
        language = normalize_lang_hint(lang_hint)
        with self._lock:
            try:
                import mlx_whisper  # noqa: F401
            except ImportError:
                return self._transcribe_faster(media, language)
            return self._transcribe_mlx(media, language)

    def _transcribe_mlx(
        self, media: Path, lang_hint: str | None
    ) -> tuple[list[TranscriptSegment], str | None]:
        import mlx_whisper

        result = mlx_whisper.transcribe(
            str(media), path_or_hf_repo=MLX_REPO, word_timestamps=True, language=lang_hint
        )
        segments = [
            TranscriptSegment(
                start_s=float(s["start"]), end_s=float(s["end"]), text=str(s["text"]).strip()
            )
            for s in result.get("segments", [])
            if str(s.get("text", "")).strip()
        ]
        return segments, result.get("language")

    def _transcribe_faster(
        self, media: Path, lang_hint: str | None
    ) -> tuple[list[TranscriptSegment], str | None]:
        from faster_whisper import WhisperModel

        if self._faster_model is None:
            self._faster_model = WhisperModel(self._model_name, device="auto", compute_type="auto")
        raw_segments, info = self._faster_model.transcribe(
            str(media), word_timestamps=True, language=lang_hint
        )
        segments = [
            TranscriptSegment(start_s=float(s.start), end_s=float(s.end), text=s.text.strip())
            for s in raw_segments
            if s.text.strip()
        ]
        return segments, getattr(info, "language", None)
