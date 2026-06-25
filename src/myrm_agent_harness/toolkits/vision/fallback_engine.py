"""Vision Fallback Engine

[INPUT]
myrm_agent_harness.core.config.llm::LLMConfig (POS: 框架层大模型配置定义)
myrm_agent_harness.toolkits.llms.core.llm::create_litellm_model (POS: 框架层大模型创建器)
myrm_agent_harness.utils.media.image_compressor::image_compressor (POS: 图像压缩工具)

[OUTPUT]
VisionFallbackEngine: 提供使用辅助视觉模型将图像转为文本描述的服务，支持异常时自适应压缩重试。

[POS]
视觉能力降级服务。在主模型缺乏视觉能力时，提供底层、无状态的图像转文本能力。

提供纯粹的、无状态的底层图像转文字降级服务。
封装了图像并发解析与基于 image_compressor 的 Reactive Resize 兜底策略。
属于 Harness 框架层的工具包，供业务层与框架工具链调用，绝不依赖任何业务逻辑和数据库。
"""

import asyncio
import base64
import io
import logging
from typing import Protocol

from langchain_core.messages import HumanMessage

from myrm_agent_harness.core.config.llm import LLMConfig
from myrm_agent_harness.toolkits.llms.core.llm import create_litellm_model
from myrm_agent_harness.utils.media.image_compressor import image_compressor

logger = logging.getLogger(__name__)


class FileExecutor(Protocol):
    async def read_file_bytes(self, path: str) -> bytes: ...


class VisionFallbackEngine:
    """视觉回退引擎

    使用辅助视觉大模型对图像进行深度解析，将多模态数据转为纯文本，
    彻底解决无视觉主模型无法处理图像的痛点。
    """

    # 解析图像时使用的固定 Prompt
    _VISION_PROMPT = (
        "You are an expert vision analysis AI. Please provide a detailed, accurate, "
        "and comprehensive text description of this image. If there is text, code, "
        "or console output in the image, transcribe the important parts exactly. "
        "If it is a UI screenshot, describe its layout and key elements. "
        "Output ONLY the description."
    )

    def __init__(self, fallback_config: LLMConfig):
        """初始化引擎

        Args:
            fallback_config: 辅助视觉大模型的配置，必须支持 vision (例如 gpt-4o-mini)
        """
        self.fallback_config = fallback_config
        # 温度尽量低，保证解析的确定性和代码抄写的准确性
        self.model = create_litellm_model(
            model=fallback_config.model,
            api_key=fallback_config.api_key,
            base_url=fallback_config.base_url,
            temperature=0.1,
            streaming=False,
            **(fallback_config.model_kwargs or {}),
        )

    async def describe_image_b64(
        self,
        b64_data: str,
        mime_type: str = "image/jpeg",
        retry_count: int = 1,
        prompt: str | None = None,
    ) -> str:
        """解析单张 Base64 格式的图片 (带 Reactive Resize 兜底)

        Args:
            b64_data: Base64 编码的图片数据
            mime_type: MIME 类型
            retry_count: 剩余重试次数
            prompt: 自定义 prompt，默认使用通用图像分析 prompt
        """
        effective_prompt = prompt or self._VISION_PROMPT
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
            err_str = str(e).lower()
            # 捕获 413 Payload Too Large / 415 异常进行 Reactive Resize
            if retry_count > 0 and (
                "413" in err_str or "payload too large" in err_str or "415" in err_str or "too large" in err_str
            ):
                logger.warning(
                    "Vision API rejected payload due to size (%s). Triggering Reactive Resize...",
                    e,
                )
                try:
                    # 将 base64 转回 bytes
                    raw_bytes = base64.b64decode(b64_data)
                    buffer = io.BytesIO(raw_bytes)

                    # 质量压缩
                    compressed_bytes = image_compressor.compress(buffer, quality=0.5)
                    if compressed_bytes:
                        compressed_b64 = base64.b64encode(compressed_bytes).decode("ascii")
                        logger.info("Reactive Resize successful. Retrying vision fallback...")
                        return await self.describe_image_b64(compressed_b64, mime_type, retry_count=0, prompt=prompt)
                    else:
                        logger.warning("Image compression returned empty. Fallback failed.")
                except Exception as comp_err:
                    logger.error("Reactive Resize failed: %s", comp_err)

            logger.error("Vision Fallback Engine failed to describe image: %s", e)
            return f"[Vision Analysis Failed: {e!s}]"

    async def describe_images_b64(self, images: list[tuple[str, str]]) -> list[str]:
        """并发解析多张 Base64 格式的图片

        Args:
            images: 列表，每一项为 (b64_data, mime_type)
        Returns:
            对应的文本描述列表
        """
        tasks = [self.describe_image_b64(b64, mime) for b64, mime in images]
        results = await asyncio.gather(*tasks, return_exceptions=False)
        return list(results)

    async def describe_local_image(self, path: str, executor: FileExecutor) -> str:
        """通过文件沙箱执行器解析本地图像文件"""
        import base64
        from pathlib import PurePosixPath

        from myrm_agent_harness.utils.mime_types import IMAGE_MIME_TYPES as MIME_TYPES

        suffix = PurePosixPath(path).suffix.lower()
        mime_type = MIME_TYPES.get(suffix, "image/png")

        try:
            raw_bytes = await executor.read_file_bytes(path)
        except Exception as e:
            return f"[Failed to read local image {path}: {e}]"

        b64_data = base64.standard_b64encode(raw_bytes).decode("ascii")
        return await self.describe_image_b64(b64_data, mime_type)
