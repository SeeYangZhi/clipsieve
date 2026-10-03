import subprocess
from pathlib import Path

from clipsieve.evidence.frames import FakeFrames, FfmpegFrames, FrameExtractor


def test_fake_frames_writes_hook_first(tmp_path):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"\x00")
    dest = tmp_path / "frames"
    frames = FakeFrames(count=3).extract(video, dest, max_frames=8)
    assert [p.name for p in frames] == ["hook.jpg", "scene_01.jpg", "scene_02.jpg"]
    assert all(p.is_file() for p in frames)


def test_fake_frames_respects_cap(tmp_path):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"\x00")
    frames = FakeFrames(count=10).extract(video, tmp_path / "f", max_frames=4)
    assert len(frames) == 4


def test_hook_argv():
    argv = FfmpegFrames().build_hook_argv(Path("/v/video.mp4"), Path("/v/frames"))
    assert argv[:3] == ["ffmpeg", "-hide_banner", "-loglevel"]
    assert "-ss" in argv and argv[argv.index("-ss") + 1] == "0.5"
    assert argv[-1] == "/v/frames/hook.jpg"
    assert "-frames:v" in argv and argv[argv.index("-frames:v") + 1] == "1"


def test_scene_argv_uses_threshold_and_cap():
    argv = FfmpegFrames(scene_threshold=0.3).build_scene_argv(
        Path("/v/video.mp4"), Path("/v/frames"), max_frames=8
    )
    vf = argv[argv.index("-vf") + 1]
    assert "select='gt(scene,0.3)'" in vf and "scale=640:-2" in vf
    assert argv[argv.index("-frames:v") + 1] == "7"  # hook frame takes one slot
    assert argv[-1] == "/v/frames/scene_%02d.jpg"


def test_ffmpeg_frames_collects_outputs_in_order(tmp_path, monkeypatch):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"\x00")
    dest = tmp_path / "frames"

    def fake_run(argv, check, capture_output):
        out = Path(argv[-1])
        out.parent.mkdir(parents=True, exist_ok=True)
        if out.name == "hook.jpg":
            out.write_bytes(b"h")
        else:
            for i in (1, 2, 3):
                (out.parent / f"scene_{i:02d}.jpg").write_bytes(b"s")
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr("clipsieve.evidence.frames.subprocess.run", fake_run)
    frames = FfmpegFrames().extract(video, dest, max_frames=3)
    assert [p.name for p in frames] == ["hook.jpg", "scene_01.jpg", "scene_02.jpg"]


def test_protocol_conformance():
    assert isinstance(FakeFrames(), FrameExtractor)
    assert isinstance(FfmpegFrames(), FrameExtractor)


def test_ffmpeg_frames_tolerates_no_scene_changes(tmp_path, monkeypatch):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"\x00")

    def fake_run(argv, check, capture_output):
        out = Path(argv[-1])
        out.parent.mkdir(parents=True, exist_ok=True)
        if out.name == "hook.jpg":
            out.write_bytes(b"h")
            return subprocess.CompletedProcess(argv, 0)
        return subprocess.CompletedProcess(argv, 234)

    monkeypatch.setattr("clipsieve.evidence.frames.subprocess.run", fake_run)
    frames = FfmpegFrames().extract(video, tmp_path / "frames", max_frames=8)
    assert [p.name for p in frames] == ["hook.jpg"]
