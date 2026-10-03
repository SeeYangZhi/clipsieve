from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from clipsieve.logging import get_logger

log = get_logger(__name__)


def ocr_lang_for_post(lang: str | None) -> str:
    return "ch" if (lang or "").lower().startswith("zh") else "en"


@runtime_checkable
class OCR(Protocol):
    def read(self, image: Path, lang: str) -> list[str]: ...


class FakeOCR:
    """Returns the `<image>.ocr.json` sidecar (a JSON list of strings) when present, else nothing.

    A malformed sidecar raises, like `read_sidecar_transcript`.
    """

    def read(self, image: Path, lang: str) -> list[str]:
        sidecar = image.with_name(image.name + ".ocr.json")
        if not sidecar.exists():
            return []
        return [str(t) for t in json.loads(sidecar.read_text(encoding="utf-8"))]


class PaddleOCRBackend:
    """PaddleOCR with one lazily built engine per language. Lines below `min_confidence` drop.

    Targets the paddleocr 2.x API; the `ocr` extra pins `paddleocr<3`.
    """

    def __init__(self, min_confidence: float = 0.6) -> None:
        self._min_confidence = min_confidence
        self._engines: dict[str, Any] = {}

    def _engine(self, lang: str) -> Any:
        if lang not in self._engines:
            from paddleocr import PaddleOCR

            self._engines[lang] = PaddleOCR(use_angle_cls=True, lang=lang, show_log=False)
        return self._engines[lang]

    def read(self, image: Path, lang: str) -> list[str]:
        result = self._engine(lang).ocr(str(image), cls=True)
        lines: list[str] = []
        for page in result or []:
            for item in page or []:
                try:
                    text, conf = item[1]
                except (IndexError, TypeError, ValueError):
                    continue
                if float(conf) >= self._min_confidence and str(text).strip():
                    lines.append(str(text).strip())
        log.debug("ocr.done", image=str(image), lines=len(lines))
        return lines
