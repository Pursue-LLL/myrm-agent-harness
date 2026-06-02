"""图片文件读取模块

为 file_read_tool 提供图片文件的多模态读取能力。
当 Agent 读取图片文件时，返回 LangChain content blocks，让模型直接"看到"图片。

设计原则：
- 支持 vision 的模型：返回 [文本描述, 图片内容块]（provider-agnostic）
- 不支持 vision 的模型：返回纯文本描述（文件名、大小、格式）
- <= 5MB：原始 base64 直传（零损失，所有 provider 安全）
- 5-20MB：Reactive Compress — 压缩到 max_dimension=4096 后传给模型
- > 20MB：降级为纯文本描述

[INPUT]
- toolkits.code_execution.executors.base::CodeExecutor (POS: Code executor base classes.)

[OUTPUT]
- is_image_path: function — is_image_path
- read_image_as_content_blocks: function — read_image_as_content_blocks

[POS]
Provides is_image_path, read_image_as_content_blocks.
"""

from __future__ import annotations

import base64
import io
import logging
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from langchain_core.messages.content import ContentBlock, create_image_block, create_text_block

from myrm_agent_harness.utils.image_utils import MAX_IMAGE_PAYLOAD_BYTES, MAX_IMAGE_READ_BYTES
from myrm_agent_harness.utils.mime_types import IMAGE_EXTENSIONS
from myrm_agent_harness.utils.mime_types import IMAGE_MIME_TYPES as MIME_TYPES

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.code_execution.executors.base import CodeExecutor

logger = logging.getLogger(__name__)

_INLINE_THRESHOLD = 5 * 1024 * 1024


def is_image_path(path: str) -> bool:
    """检测路径是否为图片文件"""
    suffix = PurePosixPath(path).suffix.lower()
    return suffix in IMAGE_EXTENSIONS


async def read_image_as_content_blocks(
    path: str, executor: CodeExecutor, supports_vision: bool
) -> str | list[ContentBlock]:
    """读取图片文件并返回适当格式的内容"""
    suffix = PurePosixPath(path).suffix.lower()
    mime_type = MIME_TYPES.get(suffix, "image/png")

    try:
        raw_bytes = await executor.read_file_bytes(path)
    except FileNotFoundError:
        raise
    except Exception as e:
        logger.warning("Failed to read image bytes: %s, error: %s", path, e)
        return f"[Image file: {path}] (Failed to read: {e})"

    size_bytes = len(raw_bytes)
    size_display = _format_size(size_bytes)

    if not supports_vision:
        return f"[Image file: {path}] ({mime_type}, {size_display}. Current model does not support vision.)"

    if size_bytes > MAX_IMAGE_READ_BYTES:
        return (
            f"[Image file: {path}] ({mime_type}, {size_display}. "
            f"Exceeds {_format_size(MAX_IMAGE_READ_BYTES)} limit for reading into memory. "
            f"Use bash_tool to process or resize.)"
        )

    if _needs_compression(raw_bytes):
        compressed_bytes = _reactive_compress(raw_bytes)
        if compressed_bytes is None:
            return (
                f"[Image file: {path}] ({mime_type}, {size_display}. "
                f"Compression failed. Use bash_tool to process or resize.)"
            )
        raw_bytes = compressed_bytes
        size_bytes = len(raw_bytes)
        mime_type = "image/jpeg"
        logger.info(
            "Image %s compressed: %s -> %s",
            path, size_display, _format_size(size_bytes),
        )

    if size_bytes > MAX_IMAGE_PAYLOAD_BYTES:
        return (
            f"[Image file: {path}] ({mime_type}, {_format_size(size_bytes)}. "
            f"Exceeds {_format_size(MAX_IMAGE_PAYLOAD_BYTES)} API payload limit even after compression. "
            f"Use bash_tool to process or resize.)"
        )

    b64 = base64.standard_b64encode(raw_bytes).decode("ascii")

    return [
        create_text_block(f"[Image: {path}] ({mime_type}, {size_display})"),
        create_image_block(base64=b64, mime_type=mime_type),
    ]


def _needs_compression(raw_bytes: bytes) -> bool:
    """Check if image needs compression based on file size or resolution."""
    if len(raw_bytes) > _INLINE_THRESHOLD:
        return True
    try:
        from PIL import Image

        Image.MAX_IMAGE_PIXELS = None  # Prevent DecompressionBombError for large resolutions
        with Image.open(io.BytesIO(raw_bytes)) as img:
            w, h = img.size
            return w > 4096 or h > 4096
    except Exception as e:
        logger.debug("Failed to check image resolution: %s", e)
        return False


def _reactive_compress(raw_bytes: bytes) -> bytes | None:
    """Compress oversized image to JPEG with max 4096px dimension.

    Always outputs JPEG regardless of input format — JPEG is universally
    supported and achieves much better compression for photographic content.
    """
    try:
        from PIL import Image, ImageOps

        Image.MAX_IMAGE_PIXELS = None  # Prevent DecompressionBombError
        img = Image.open(io.BytesIO(raw_bytes))
        img = ImageOps.exif_transpose(img)
        w, h = img.size
        max_dim = 4096
        if w > max_dim or h > max_dim:
            ratio = min(max_dim / w, max_dim / h)
            img = img.resize((int(w * ratio), int(h * ratio)), Image.Resampling.LANCZOS)

        if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
            img = img.convert("RGBA")
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[3])
            img = bg
        elif img.mode != "RGB":
            img = img.convert("RGB")

        out = io.BytesIO()
        img.save(out, format="JPEG", quality=80, optimize=True)
        return out.getvalue()
    except Exception as e:
        logger.warning("Reactive image compression failed: %s", e)
        return None


def _format_size(size_bytes: int) -> str:
    """格式化文件大小"""
    if size_bytes < 1024:
        return f"{size_bytes}B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f}KB"
    return f"{size_bytes / (1024 * 1024):.1f}MB"
