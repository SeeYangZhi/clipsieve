import json
import sys
import threading
import time
import types
from concurrent.futures import ThreadPoolExecutor

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


def test_paddle_backend_serialises_engine_construction_and_inference(tmp_path, monkeypatch):
    # The Runner extracts two posts at once (asyncio.to_thread) with one shared backend.
    guard = threading.Lock()
    inside = {"now": 0, "peak": 0}
    constructed: list[str] = []

    def enter():
        with guard:
            inside["now"] += 1
            inside["peak"] = max(inside["peak"], inside["now"])
        time.sleep(0.05)

    def leave():
        with guard:
            inside["now"] -= 1

    fake = types.ModuleType("paddleocr")

    class PaddleOCR:
        def __init__(self, use_angle_cls, lang, show_log):
            enter()
            constructed.append(lang)
            leave()

        def ocr(self, path, cls):
            enter()
            leave()
            return [[[[[0, 0], [1, 0], [1, 1], [0, 1]], ("TEXT", 0.99)]]]

    fake.PaddleOCR = PaddleOCR
    monkeypatch.setitem(sys.modules, "paddleocr", fake)
    images = [tmp_path / "a.jpg", tmp_path / "b.jpg"]
    for img in images:
        img.write_bytes(b"\xff")
    backend = PaddleOCRBackend()
    start = threading.Barrier(2)

    def run(img):
        start.wait()
        return backend.read(img, "en")

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(run, images)) == [["TEXT"], ["TEXT"]]
    assert constructed == ["en"], "one engine per language"
    assert inside["peak"] == 1
