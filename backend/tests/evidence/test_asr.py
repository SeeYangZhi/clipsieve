import json
import sys
import threading
import time
import types
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from clipsieve.evidence.asr import (
    ASR,
    FakeASR,
    WhisperASR,
    normalize_lang_hint,
    read_sidecar_transcript,
)


def _write_sidecar(media: Path, with_lang: bool = True) -> None:
    payload: dict = {"segments": [{"start_s": 0.0, "end_s": 2.0, "text": "刚到上海"}]}
    if with_lang:
        payload["lang"] = "zh-Hans"
    media.with_name(media.name + ".transcript.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


def test_fake_asr_returns_sidecar(tmp_path):
    media = tmp_path / "video.mp4"
    media.write_bytes(b"\x00")
    _write_sidecar(media)
    segments, lang = FakeASR().transcribe(media, None)
    assert lang == "zh-Hans" and segments[0].text == "刚到上海"


def test_fake_asr_without_sidecar_is_empty(tmp_path):
    media = tmp_path / "video.mp4"
    media.write_bytes(b"\x00")
    assert FakeASR().transcribe(media, "en") == ([], None)


def test_read_sidecar_none_when_missing(tmp_path):
    assert read_sidecar_transcript(tmp_path / "x.mp4") is None


def test_read_sidecar_tolerates_missing_lang(tmp_path):
    media = tmp_path / "video.mp4"
    media.write_bytes(b"\x00")
    _write_sidecar(media, with_lang=False)
    result = read_sidecar_transcript(media)
    assert result is not None
    segments, lang = result
    assert lang is None and segments[0].text == "刚到上海"
    assert FakeASR().transcribe(media, None)[1] is None


def test_fake_asr_empty_sidecar_is_not_none(tmp_path):
    media = tmp_path / "video.mp4"
    media.write_bytes(b"\x00")
    media.with_name(media.name + ".transcript.json").write_text(
        '{"lang": "en", "segments": []}', encoding="utf-8"
    )
    assert read_sidecar_transcript(media) == ([], "en")
    assert FakeASR().transcribe(media, None) == ([], "en")


def test_whisper_asr_prefers_sidecar_and_never_loads_model(tmp_path, monkeypatch):
    media = tmp_path / "video.mp4"
    media.write_bytes(b"\x00")
    _write_sidecar(media)
    asr = WhisperASR()

    def boom(*a, **k):
        raise AssertionError("model loaded")

    monkeypatch.setattr(asr, "_transcribe_mlx", boom)
    monkeypatch.setattr(asr, "_transcribe_faster", boom)
    segments, lang = asr.transcribe(media, None)
    assert lang == "zh-Hans" and len(segments) == 1


@pytest.mark.parametrize(
    ("hint", "language"), [("en-US", "en"), ("xx", None), (None, None)], ids=str
)
def test_whisper_asr_uses_mlx_when_importable(tmp_path, monkeypatch, hint, language):
    media = tmp_path / "video.mp4"
    media.write_bytes(b"\x00")
    fake_mlx = types.ModuleType("mlx_whisper")
    received: list[str | None] = []

    def transcribe(path, path_or_hf_repo, word_timestamps, language):
        assert word_timestamps is True
        received.append(language)
        return {
            "language": "en",
            "segments": [{"start": 0.0, "end": 1.5, "text": " hello there "}],
        }

    fake_mlx.transcribe = transcribe
    monkeypatch.setitem(sys.modules, "mlx_whisper", fake_mlx)
    segments, lang = WhisperASR().transcribe(media, hint)
    assert lang == "en" and segments[0].text == "hello there" and segments[0].end_s == 1.5
    assert received == [language], "mlx-whisper gets the normalised language hint"


def test_whisper_asr_falls_back_to_faster_whisper(tmp_path, monkeypatch):
    media = tmp_path / "video.mp4"
    media.write_bytes(b"\x00")
    monkeypatch.setitem(sys.modules, "mlx_whisper", None)  # import raises ImportError
    fake_fw = types.ModuleType("faster_whisper")
    received: list[str | None] = []

    class WhisperModel:
        def __init__(self, name, device="auto", compute_type="auto"):
            assert name == "large-v3"

        def transcribe(self, path, word_timestamps, language):
            received.append(language)
            Seg = types.SimpleNamespace
            return iter([Seg(start=0.0, end=2.0, text=" 你好 ")]), types.SimpleNamespace(
                language="zh"
            )

    fake_fw.WhisperModel = WhisperModel
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_fw)
    segments, lang = WhisperASR().transcribe(media, "zh-Hans")
    assert lang == "zh" and segments[0].text == "你好"
    assert received == ["zh"], "faster-whisper gets the normalised language hint"


def test_protocol_conformance():
    assert isinstance(FakeASR(), ASR)
    assert isinstance(WhisperASR(), ASR)


@pytest.mark.parametrize(
    ("hint", "expected"),
    [
        ("zh-Hans", "zh"),
        ("zh-Hant-TW", "zh"),
        ("en-US", "en"),
        ("EN", "en"),
        ("pt_BR", "pt"),
        ("yue", "yue"),
        ("haw", "haw"),
        ("iw", "he"),
        ("xx", None),
        ("", None),
        (None, None),
    ],
)
def test_normalize_lang_hint(hint, expected):
    assert normalize_lang_hint(hint) == expected


class _Overlap:
    """Counts callers inside a section at once; `peak` must stay 1 when callers are serialised."""

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self.inside = 0
        self.peak = 0

    def __enter__(self) -> None:
        with self._guard:
            self.inside += 1
            self.peak = max(self.peak, self.inside)
        time.sleep(0.05)

    def __exit__(self, *exc) -> None:
        with self._guard:
            self.inside -= 1


def test_whisper_asr_serialises_model_construction_and_inference(tmp_path, monkeypatch):
    # The Runner extracts two posts at once (asyncio.to_thread) with one shared WhisperASR.
    monkeypatch.setitem(sys.modules, "mlx_whisper", None)
    fake_fw = types.ModuleType("faster_whisper")
    constructed: list[str] = []
    building, inferring = _Overlap(), _Overlap()

    class WhisperModel:
        def __init__(self, name, device="auto", compute_type="auto"):
            with building:
                constructed.append(name)

        def transcribe(self, path, word_timestamps, language):
            with inferring:
                Seg = types.SimpleNamespace
                return [Seg(start=0.0, end=1.0, text="hi")], Seg(language="en")

    fake_fw.WhisperModel = WhisperModel
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_fw)
    asr = WhisperASR()
    media = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
    for m in media:
        m.write_bytes(b"\x00")
    start = threading.Barrier(2)

    def run(m: Path):
        start.wait()
        return asr.transcribe(m, "en")

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, media))
    assert [lang for _, lang in results] == ["en", "en"]
    assert constructed == ["large-v3"], "the model is built once"
    assert building.peak == 1 and inferring.peak == 1
