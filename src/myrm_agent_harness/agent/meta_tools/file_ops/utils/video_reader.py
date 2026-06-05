"""视频文件读取模块

为 file_read_tool 提供视频文件的多模态读取能力。
当 Agent 读取视频文件时，根据模型能力返回适当格式的内容。

设计原则：
- 支持视频的模型：返回 [文本描述, 视频内容块]（直传 LLM）
- 仅支持视觉的模型：通过 VideoAnalysisEngine 帧提取降级
- 不支持视觉的模型：返回纯文本描述（文件名、大小、格式）
- 硬上限：超过 100MB 的视频降级为纯文本描述

[INPUT]
- toolkits.code_execution.executors.base::CodeExecutor (POS: Code executor base classes.)
- toolkits.vision.video_analysis_engine::VideoAnalysisEngine (POS: 视频分析引擎)

[OUTPUT]
- is_video_path: function — 检测路径是否为视频文件
- read_video_as_content_blocks: function — 读取视频文件并返回适当格式的内容

[POS]
Provides is_video_path, read_video_as_content_blocks.
"""

from __future__ import annotations

import base64
import logging
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from langchain_core.messages.content import ContentBlock, create_text_block

from myrm_agent_harness.toolkits.vision.video_analysis_engine import (
    MAX_VIDEO_BYTES,
    VIDEO_EXTENSIONS,
    VIDEO_MIME_TYPES,
)

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.code_execution.executors.base import CodeExecutor

logger = logging.getLogger(__name__)


def is_video_path(path: str) -> bool:
    """检测路径是否为视频文件"""
    suffix = PurePosixPath(path).suffix.lower()
    return suffix in VIDEO_EXTENSIONS


async def read_video_as_content_blocks(
    path: str,
    executor: CodeExecutor,
    supports_vision: bool,
    supports_video: bool = False,
    vision_fallback_model_cfg: object | None = None,
) -> str | list[ContentBlock]:
    """读取视频文件并返回适当格式的内容

    Args:
        path: 视频文件路径
        executor: 代码执行器
        supports_vision: 模型是否支持图像视觉
        supports_video: 模型是否原生支持视频
        vision_fallback_model_cfg: 视觉降级模型配置（用于帧提取分析）
    """
    suffix = PurePosixPath(path).suffix.lower()
    mime_type = VIDEO_MIME_TYPES.get(suffix, "video/mp4")

    try:
        raw_bytes = await executor.read_file_bytes(path)
    except FileNotFoundError:
        raise
    except Exception as e:
        logger.warning("Failed to read video bytes: %s, error: %s", path, e)
        return f"[Video file: {path}] (Failed to read: {e})"

    size_bytes = len(raw_bytes)
    size_display = _format_size(size_bytes)

    if not supports_vision and not supports_video:
        return f"[Video file: {path}] ({mime_type}, {size_display}. Current model does not support vision or video.)"

    if size_bytes > MAX_VIDEO_BYTES:
        return (
            f"[Video file: {path}] ({mime_type}, {size_display}. "
            f"Exceeds {_format_size(MAX_VIDEO_BYTES)} limit. "
            f"Use a shorter or smaller video.)"
        )

    if supports_video:
        b64 = base64.standard_b64encode(raw_bytes).decode("ascii")
        data_url = f"data:{mime_type};base64,{b64}"
        return [
            create_text_block(f"[Video: {path}] ({mime_type}, {size_display})"),
            {"type": "image_url", "image_url": {"url": data_url}},
        ]

    # 模型仅支持图像不支持视频 → 通过 VideoAnalysisEngine 帧提取分析
    if vision_fallback_model_cfg:
        from myrm_agent_harness.agent.config.llm import LLMConfig
        from myrm_agent_harness.toolkits.vision.video_analysis_engine import (
            VideoAnalysisEngine,
        )

        try:
            fallback_config = LLMConfig.model_validate(vision_fallback_model_cfg, from_attributes=True)
            engine = VideoAnalysisEngine(fallback_config)
            description = await engine.analyze_local_video(path, executor, supports_video=False)
            return f"[Video: {path}] ({mime_type}, {size_display})\n[Video Analysis]:\n{description}"
        except Exception as e:
            logger.warning("Video analysis fallback failed: %s", e)
            return f"[Video file: {path}] ({mime_type}, {size_display}. Video analysis failed: {e})"

    return (
        f"[Video file: {path}] ({mime_type}, {size_display}. "
        f"Model supports vision but not video. Configure a vision fallback model "
        f"or use a video-capable model for video analysis.)"
    )


def _format_size(size_bytes: int) -> str:
    """格式化文件大小"""
    if size_bytes < 1024:
        return f"{size_bytes}B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f}KB"
    return f"{size_bytes / (1024 * 1024):.1f}MB"
