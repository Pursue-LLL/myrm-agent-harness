"""Video pre-upload transcode helpers.

[INPUT]
ffmpeg binary on PATH (optional)

[OUTPUT]
transcode_video_h264, cleanup_transcode_path, has_ffmpeg

[POS]
Harness video transcode utilities. H.264 pre-upload normalization with tracked temp cleanup.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Final

logger = logging.getLogger(__name__)

DEFAULT_MAX_WIDTH = 1920
DEFAULT_FPS = 2
_TRANSCODE_DIRS: Final[set[str]] = set()


def has_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


async def transcode_video_h264(
    input_path: str,
    *,
    max_width: int = DEFAULT_MAX_WIDTH,
    fps: int = DEFAULT_FPS,
) -> str:
    """Transcode video to compact H.264 MP4. Returns output path in temp dir."""
    if not has_ffmpeg():
        raise RuntimeError("ffmpeg is required for video transcode")

    tmp_dir = tempfile.mkdtemp(prefix="vtrans_")
    output_path = str(Path(tmp_dir) / "compact.mp4")
    scale = f"scale='min({max_width},iw)':-2"
    vf = f"{scale},fps={fps}"
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        input_path,
        "-vf",
        vf,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "28",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        output_path,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    code = await proc.wait()
    if code != 0 or not Path(output_path).exists():
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise RuntimeError(f"ffmpeg transcode failed with exit code {code}")
    _TRANSCODE_DIRS.add(tmp_dir)
    return output_path


def cleanup_transcode_path(path: str) -> None:
    """Remove temp directory created by transcode_video_h264."""
    parent = Path(path).parent
    tmp_dir = str(parent)
    if tmp_dir in _TRANSCODE_DIRS:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        _TRANSCODE_DIRS.discard(tmp_dir)
