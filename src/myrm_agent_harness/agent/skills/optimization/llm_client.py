"""LLM Client with Retry

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]
- .config::PerformanceConfig (POS: 性能配置)
- .types::OptimizationError (POS: 优化错误类型)

[OUTPUT]
- LLMClient: LLM调用客户端（带重试和超时）

[POS]
Generic LLM call wrapper. Implements exponential backoff retry, timeout control, and error handling.

"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from .config import PerformanceConfig

from .types import OptimizationError

logger = logging.getLogger(__name__)


class LLMClient:
    """LLM调用客户端

    提供带重试和超时的LLM调用封装，确保鲁棒性。

    Features:
    1. 指数退避重试（Exponential Backoff）
    2. 超时控制（asyncio.wait_for）
    3. 统一错误处理
    4. 日志记录
    """

    def __init__(self, llm: BaseChatModel, config: PerformanceConfig):
        """初始化LLM客户端

        Args:
            llm: LangChain LLM实例
            config: 性能配置
        """
        self.llm = llm
        self.config = config

    async def call_with_retry(self, prompt: str) -> str:
        """带重试的LLM调用

        实现指数退避重试策略：
        - 第1次失败后等待 retry_delay * 2^0 秒
        - 第2次失败后等待 retry_delay * 2^1 秒
        - 第3次失败后等待 retry_delay * 2^2 秒
        - ...

        Args:
            prompt: LLM prompt

        Returns:
            str: LLM响应内容

        Raises:
            OptimizationError: LLM调用失败（所有重试耗尽）
        """
        from langchain_core.messages import HumanMessage

        max_retries = self.config.llm_max_retries
        retry_delay = self.config.llm_retry_delay
        timeout = self.config.llm_timeout

        for attempt in range(max_retries):
            try:
                # 调用LLM（带超时）
                response = await asyncio.wait_for(self.llm.ainvoke([HumanMessage(content=prompt)]), timeout=timeout)

                # 提取内容
                content = response.content if hasattr(response, "content") else str(response)

                logger.info(f"LLM call succeeded (attempt {attempt + 1}/{max_retries})")
                return content

            except TimeoutError:
                if attempt == max_retries - 1:
                    raise OptimizationError(f"LLM调用超时 ({timeout}秒，已重试{max_retries}次）") from None

                wait_time = retry_delay * (2**attempt)
                logger.warning(f"LLM timeout (attempt {attempt + 1}/{max_retries}), retry in {wait_time:.1f}s")
                await asyncio.sleep(wait_time)

            except Exception as e:
                if attempt == max_retries - 1:
                    raise OptimizationError(f"LLM调用失败: {e!s}") from e

                wait_time = retry_delay * (2**attempt)
                logger.warning(f"LLM error (attempt {attempt + 1}/{max_retries}): {e}, retry in {wait_time:.1f}s")
                await asyncio.sleep(wait_time)

        # 理论上不会到达这里（上面已经raise）
        raise OptimizationError("LLM optimization failed after all retries")
