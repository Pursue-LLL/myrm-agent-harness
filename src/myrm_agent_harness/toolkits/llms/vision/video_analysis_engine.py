"""Video Analysis Engine

[INPUT]
myrm_agent_harness.core.config.llm::LLMConfig (POS: 框架层大模型配置定义)
myrm_agent_harness.toolkits.llms.core.llm::create_litellm_model (POS: 框架层大模型创建器)
myrm_agent_harness.toolkits.llms.vision.fallback_engine::VisionFallbackEngine (POS: 图像降级引擎，帧分析复用)

[OUTPUT]
VideoAnalysisEngine: 视频分析引擎，支持直传和帧提取降级两种策略。

[POS]
视频分析核心引擎。在主模型支持视频时直传，不支持时通过 ffmpeg 帧提取 + 视觉模型分析实现降级。
属于 Harness 框架层的工具包，供业务层与框架工具链调用，绝不依赖任何业务逻辑和数据库。
"""

import asyncio
import base64
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path, PurePosixPath
from typing import Protocol

from langchain_core.messages import HumanMessage

from myrm_agent_harness.core.config.llm import LLMConfig
from myrm_agent_harness.toolkits.llms.core.llm import create_litellm_model

logger = logging.getLogger(__name__)

MAX_VIDEO_BYTES = 100 * 1024 * 1024  # 100MB
DEFAULT_FRAME_COUNT = 8

VIDEO_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".mp4",
        ".mov",
        ".webm",
        ".avi",
        ".mkv",
        ".flv",
        ".wmv",
        ".m4v",
    }
)

VIDEO_MIME_TYPES: dict[str, str] = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
    ".avi": "video/x-msvideo",
    ".mkv": "video/x-matroska",
    ".flv": "video/x-flv",
    ".wmv": "video/x-ms-wmv",
    ".m4v": "video/x-m4v",
}


class FileExecutor(Protocol):
    async def read_file_bytes(self, path: str) -> bytes: ...


def is_video_path(path: str) -> bool:
    """检测路径是否为视频文件"""
    suffix = PurePosixPath(path).suffix.lower()
    return suffix in VIDEO_EXTENSIONS


def _has_ffmpeg() -> bool:
    """检测 ffmpeg 是否可用"""
    return shutil.which("ffmpeg") is not None


async def _extract_frames_ffmpeg(
    video_path: str,
    frame_count: int = DEFAULT_FRAME_COUNT,
) -> list[tuple[bytes, str]]:
    """使用 ffmpeg 从视频中提取关键帧

    优先使用 scene change detection，回退到均匀采样。

    Returns:
        list of (frame_bytes, mime_type) tuples
    """
    with tempfile.TemporaryDirectory(prefix="vae_") as tmp_dir:
        output_pattern = str(Path(tmp_dir) / "frame_%04d.jpg")

        # scene change detection: 提取场景切换帧（最多 frame_count 帧）
        cmd = [
            "ffmpeg",
            "-i",
            video_path,
            "-vf",
            "select='gt(scene\\,0.3)',setpts=N/FRAME_RATE/TB",
            "-frames:v",
            str(frame_count),
            "-q:v",
            "3",
            "-y",
            output_pattern,
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        await proc.wait()

        frames = sorted(Path(tmp_dir).glob("frame_*.jpg"))

        # 如果 scene detection 提取不到足够帧，回退到均匀采样
        if len(frames) < 2:
            for f in frames:
                f.unlink()

            cmd_uniform = [
                "ffmpeg",
                "-i",
                video_path,
                "-vf",
                f"fps=1/{max(1, 30 // frame_count)}",
                "-frames:v",
                str(frame_count),
                "-q:v",
                "3",
                "-y",
                output_pattern,
            ]
            proc2 = await asyncio.create_subprocess_exec(
                *cmd_uniform,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            await proc2.wait()
            frames = sorted(Path(tmp_dir).glob("frame_*.jpg"))

        result: list[tuple[bytes, str]] = []
        for frame_path in frames[:frame_count]:
            result.append((frame_path.read_bytes(), "image/jpeg"))

        return result


class VideoAnalysisEngine:
    """视频分析引擎

    支持两种策略：
    1. 直传模式：模型原生支持视频 → 构建 video content block 直接传给 LLM
    2. 帧提取降级：模型不支持视频 → ffmpeg 提取关键帧 → 视觉模型分析多帧
    """

    _VIDEO_PROMPT = (
        "You are an expert video analysis AI. Analyze the video content and provide "
        "a detailed, accurate, and comprehensive description. Include key scenes, "
        "actions, text overlays, and important visual elements. Output ONLY the description."
    )

    _FRAME_PROMPT = (
        "You are analyzing key frames extracted from a video. "
        "For each frame, briefly describe what you see. "
        "Then provide an overall summary of the video content. "
        "Output ONLY the description."
    )

    def __init__(self, fallback_config: LLMConfig):
        """初始化引擎

        Args:
            fallback_config: 辅助视觉/视频模型的配置
        """
        self.fallback_config = fallback_config
        self.model = create_litellm_model(
            model=fallback_config.model,
            api_key=fallback_config.api_key,
            base_url=fallback_config.base_url,
            temperature=0.1,
            streaming=False,
            **(fallback_config.model_kwargs or {}),
        )

    async def analyze_video_b64(
        self,
        b64_data: str,
        mime_type: str = "video/mp4",
        supports_video: bool = True,
        prompt: str | None = None,
    ) -> str:
        """分析 Base64 编码的视频

        Args:
            b64_data: Base64 编码的视频数据
            mime_type: 视频 MIME 类型
            supports_video: 目标模型是否原生支持视频
            prompt: 自定义分析提示词
        """
        if supports_video:
            return await self._direct_analyze(b64_data, mime_type, prompt)
        return await self._frame_extraction_analyze_b64(b64_data, mime_type, prompt)

    async def analyze_video_url(
        self,
        url: str,
        mime_type: str = "video/mp4",
        supports_video: bool = True,
        prompt: str | None = None,
    ) -> str:
        """分析 URL 引用的视频"""
        if supports_video:
            effective_prompt = prompt or self._VIDEO_PROMPT
            msg = HumanMessage(
                content=[
                    {"type": "text", "text": effective_prompt},
                    {"type": "image_url", "image_url": {"url": url}},
                ]
            )
            try:
                response = await self.model.ainvoke([msg])
                return str(response.content)
            except Exception as e:
                logger.error("Video URL analysis failed: %s", e)
                return f"[Video Analysis Failed: {e}]"
        return "[Video analysis requires a video-capable model or ffmpeg for frame extraction]"

    async def analyze_local_video(
        self,
        path: str,
        executor: FileExecutor,
        supports_video: bool = True,
        prompt: str | None = None,
    ) -> str:
        """通过文件执行器分析本地视频文件"""
        suffix = PurePosixPath(path).suffix.lower()
        mime_type = VIDEO_MIME_TYPES.get(suffix, "video/mp4")

        if supports_video:
            try:
                raw_bytes = await executor.read_file_bytes(path)
            except Exception as e:
                return f"[Failed to read video {path}: {e}]"

            if len(raw_bytes) > MAX_VIDEO_BYTES:
                return (
                    f"[Video too large: {len(raw_bytes) / 1024 / 1024:.1f}MB, "
                    f"limit {MAX_VIDEO_BYTES // 1024 // 1024}MB]"
                )
            b64_data = base64.standard_b64encode(raw_bytes).decode("ascii")
            return await self._direct_analyze(b64_data, mime_type, prompt)

        # 帧提取降级：需要本地文件路径（不经过 executor）
        if not _has_ffmpeg():
            return (
                "[Video analysis unavailable: current model does not support video, "
                "and ffmpeg is not installed for frame extraction. "
                "Install ffmpeg or use a video-capable model (e.g. Gemini, Claude).]"
            )

        return await self._frame_extraction_analyze_path(path, prompt)

    async def _direct_analyze(
        self,
        b64_data: str,
        mime_type: str,
        prompt: str | None = None,
    ) -> str:
        """直传模式：构建 video content block 直接传 LLM"""
        effective_prompt = prompt or self._VIDEO_PROMPT
        data_url = f"data:{mime_type};base64,{b64_data}"
        msg = HumanMessage(
            content=[
                {"type": "text", "text": effective_prompt},
                {"type": "image_url", "image_url": {"url": data_url}},
            ]
        )
        try:
            response = await self.model.ainvoke([msg])
            return str(response.content)
        except Exception as e:
            logger.error("Video direct analysis failed: %s", e)
            return f"[Video Analysis Failed: {e}]"

    async def _frame_extraction_analyze_b64(
        self,
        b64_data: str,
        mime_type: str,
        prompt: str | None = None,
    ) -> str:
        """帧提取降级：b64 视频 → 写入临时文件 → ffmpeg 提取帧 → 视觉分析"""
        if not _has_ffmpeg():
            return (
                "[Video analysis unavailable: current model does not support video, "
                "and ffmpeg is not installed for frame extraction. "
                "Install ffmpeg or use a video-capable model (e.g. Gemini, Claude).]"
            )

        suffix = ".mp4"
        for ext, mt in VIDEO_MIME_TYPES.items():
            if mt == mime_type:
                suffix = ext
                break

        with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
            tmp.write(base64.b64decode(b64_data))
            tmp.flush()
            return await self._frame_extraction_analyze_path(tmp.name, prompt)

    async def _frame_extraction_analyze_path(
        self,
        video_path: str,
        prompt: str | None = None,
    ) -> str:
        """帧提取降级：本地视频路径 → ffmpeg 提取帧 → 视觉模型分析多帧"""
        try:
            frames = await _extract_frames_ffmpeg(video_path)
        except Exception as e:
            logger.error("Frame extraction failed: %s", e)
            return f"[Video frame extraction failed: {e}]"

        if not frames:
            return "[No frames could be extracted from the video]"

        effective_prompt = prompt or self._FRAME_PROMPT
        content_blocks: list[dict[str, object]] = [{"type": "text", "text": effective_prompt}]

        for i, (frame_bytes, frame_mime) in enumerate(frames):
            frame_b64 = base64.b64encode(frame_bytes).decode("ascii")
            content_blocks.append({"type": "text", "text": f"--- Frame {i + 1}/{len(frames)} ---"})
            content_blocks.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{frame_mime};base64,{frame_b64}"},
                }
            )

        msg = HumanMessage(content=content_blocks)
        try:
            response = await self.model.ainvoke([msg])
            return str(response.content)
        except Exception as e:
            logger.error("Frame analysis failed: %s", e)
            return f"[Video Frame Analysis Failed: {e}]"
