from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Protocol, runtime_checkable

from clipsieve.logging import get_logger

log = get_logger(__name__)

HOOK_FRAME_AT_S = 0.5

PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d4944415478"
    "9c6360000002000154a24f5d0000000049454e44ae426082"
)


@runtime_checkable
class FrameExtractor(Protocol):
    def extract(self, video: Path, dest: Path, max_frames: int = 8) -> list[Path]: ...


class FakeFrames:
    """Writes `count` tiny PNG files named like the real extractor. No ffmpeg."""

    def __init__(self, count: int = 2) -> None:
        self._count = count

    def extract(self, video: Path, dest: Path, max_frames: int = 8) -> list[Path]:
        dest.mkdir(parents=True, exist_ok=True)
        names = ["hook.jpg"] + [f"scene_{i:02d}.jpg" for i in range(1, self._count)]
        out: list[Path] = []
        for name in names[:max_frames]:
            p = dest / name
            p.write_bytes(PNG_1X1)
            out.append(p)
        return out


class FfmpegFrames:
    def __init__(
        self, ffmpeg_bin: str = "ffmpeg", scene_threshold: float = 0.3, width: int = 640
    ) -> None:
        self._bin = ffmpeg_bin
        self._threshold = scene_threshold
        self._width = width

    def build_hook_argv(self, video: Path, dest: Path) -> list[str]:
        return [
            self._bin,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            str(HOOK_FRAME_AT_S),
            "-i",
            str(video),
            "-frames:v",
            "1",
            "-vf",
            f"scale={self._width}:-2",
            str(dest / "hook.jpg"),
        ]

    def build_scene_argv(self, video: Path, dest: Path, max_frames: int) -> list[str]:
        scene_cap = max(0, max_frames - 1)
        return [
            self._bin,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(video),
            "-vf",
            f"select='gt(scene,{self._threshold})',scale={self._width}:-2",
            "-vsync",
            "vfr",
            "-frames:v",
            str(scene_cap),
            str(dest / "scene_%02d.jpg"),
        ]

    def extract(self, video: Path, dest: Path, max_frames: int = 8) -> list[Path]:
        dest.mkdir(parents=True, exist_ok=True)
        for stale in [dest / "hook.jpg", *dest.glob("scene_*.jpg")]:
            stale.unlink(missing_ok=True)
        subprocess.run(self.build_hook_argv(video, dest), check=True, capture_output=True)
        if max_frames > 1:
            # A video with no scene change writes nothing and ffmpeg exits non-zero: not an error.
            scene = subprocess.run(
                self.build_scene_argv(video, dest, max_frames), check=False, capture_output=True
            )
            if scene.returncode != 0 and not any(dest.glob("scene_*.jpg")):
                log.debug("frames_no_scene_changes", video=str(video), returncode=scene.returncode)
        frames = [dest / "hook.jpg"] if (dest / "hook.jpg").exists() else []
        frames += sorted(dest.glob("scene_*.jpg"))
        frames = frames[:max_frames]
        log.debug("frames_extracted", video=str(video), count=len(frames))
        return frames
