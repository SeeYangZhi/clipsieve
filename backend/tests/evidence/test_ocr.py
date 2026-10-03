import json
import sys
import types

import pytest

from clipsieve.evidence.ocr import OCR, FakeOCR, PaddleOCRBackend, ocr_lang_for_post


def test_lang_mapping():
    assert ocr_lang_for_post("zh") == "ch"
    assert ocr_lang_for_post("zh-Hans") == "ch"
    assert ocr_lang_for_post("en") == "en"
    assert ocr_lang_for_post(None) == "en"


def test_fake_ocr_reads_sidecar(tmp_path):
    img = tmp_path / "hook.jpg"
    img.write_bytes(b"\xff")
    img.with_name("hook.jpg.ocr.json").write_text(
        json.dumps(["房租 8000", "STOP SCROLLING"], ensure_ascii=False), encoding="utf-8"
    )
    assert FakeOCR().read(img, "ch") == ["房租 8000", "STOP SCROLLING"]


def test_fake_ocr_without_sidecar_is_empty(tmp_path):
    img = tmp_path / "hook.jpg"
    img.write_bytes(b"\xff")
    assert FakeOCR().read(img, "en") == []


def test_paddle_backend_filters_low_confidence_and_caches_per_lang(tmp_path, monkeypatch):
    constructed = []
    fake = types.ModuleType("paddleocr")

    class PaddleOCR:
        def __init__(self, use_angle_cls, lang, show_log):
            constructed.append(lang)

        def ocr(self, path, cls):
            return [
                [
                    [[[0, 0], [1, 0], [1, 1], [0, 1]], ("STOP SCROLLING", 0.97)],
                    [[[0, 0], [1, 0], [1, 1], [0, 1]], ("blurry", 0.41)],
                    [[[0, 0], [1, 0], [1, 1], [0, 1]], ("房租好贵", 0.88)],
                ]
            ]

    fake.PaddleOCR = PaddleOCR
    monkeypatch.setitem(sys.modules, "paddleocr", fake)
    img = tmp_path / "f.jpg"
    img.write_bytes(b"\xff")
    backend = PaddleOCRBackend()
    assert backend.read(img, "ch") == ["STOP SCROLLING", "房租好贵"]
    backend.read(img, "ch")
    backend.read(img, "en")
    assert constructed == ["ch", "en"]


def test_paddle_backend_handles_empty_result(tmp_path, monkeypatch):
    fake = types.ModuleType("paddleocr")

    class PaddleOCR:
        def __init__(self, **kw): ...

        def ocr(self, path, cls):
            return [None]

    fake.PaddleOCR = PaddleOCR
    monkeypatch.setitem(sys.modules, "paddleocr", fake)
    img = tmp_path / "f.jpg"
    img.write_bytes(b"\xff")
    assert PaddleOCRBackend().read(img, "en") == []


def test_protocol_conformance():
    assert isinstance(FakeOCR(), OCR)
    assert isinstance(PaddleOCRBackend(), OCR)


def test_fake_ocr_malformed_sidecar_raises(tmp_path):
    img = tmp_path / "hook.jpg"
    img.write_bytes(b"\xff")
    img.with_name("hook.jpg.ocr.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        FakeOCR().read(img, "en")
