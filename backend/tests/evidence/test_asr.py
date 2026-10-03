import json
import sys
import types
from pathlib import Path

from clipsieve.evidence.asr import ASR, FakeASR, WhisperASR, read_sidecar_transcript


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


def test_whisper_asr_uses_mlx_when_importable(tmp_path, monkeypatch):
    media = tmp_path / "video.mp4"
    media.write_bytes(b"\x00")
    fake_mlx = types.ModuleType("mlx_whisper")

    def transcribe(path, path_or_hf_repo, word_timestamps, language):
        assert word_timestamps is True
        return {
            "language": "en",
            "segments": [{"start": 0.0, "end": 1.5, "text": " hello there "}],
        }

    fake_mlx.transcribe = transcribe
    monkeypatch.setitem(sys.modules, "mlx_whisper", fake_mlx)
    segments, lang = WhisperASR().transcribe(media, None)
    assert lang == "en" and segments[0].text == "hello there" and segments[0].end_s == 1.5


def test_whisper_asr_falls_back_to_faster_whisper(tmp_path, monkeypatch):
    media = tmp_path / "video.mp4"
    media.write_bytes(b"\x00")
    monkeypatch.setitem(sys.modules, "mlx_whisper", None)  # import raises ImportError
    fake_fw = types.ModuleType("faster_whisper")

    class WhisperModel:
        def __init__(self, name, device="auto", compute_type="auto"):
            assert name == "large-v3"

        def transcribe(self, path, word_timestamps, language):
            Seg = types.SimpleNamespace
            return iter([Seg(start=0.0, end=2.0, text=" 你好 ")]), types.SimpleNamespace(
                language="zh"
            )

    fake_fw.WhisperModel = WhisperModel
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_fw)
    segments, lang = WhisperASR().transcribe(media, "zh")
    assert lang == "zh" and segments[0].text == "你好"


def test_protocol_conformance():
    assert isinstance(FakeASR(), ASR)
    assert isinstance(WhisperASR(), ASR)
