"""Cloud Embedding Implementation.

Cloud API embedding backend supporting multiple providers via LiteLLM
(OpenAI, Voyage AI, Jina AI, SiliconFlow, etc.).

Features:
- Dimension management: uses preset dimensions for known models; auto-detects on first call for unknown models
- Optional cache integration (L1 LRU + L2 Redis + L3 API)
- Automatic retry on transient errors (network jitter, timeouts)

[INPUT]
retriever.embedding.base::EmbeddingService (POS: Embedding contract layer)
memory.protocols.cache::EmbeddingCacheProtocol (POS: Cache protocol for embeddings)

[OUTPUT]
CloudEmbeddingService: Concrete EmbeddingService backed by cloud APIs via LiteLLM

[POS]
Cloud embedding backend. Translates the abstract EmbeddingService interface into real
LiteLLM API calls with retry, dimension detection, and optional caching.

"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from myrm_agent_harness.toolkits.retriever.embedding.base import EmbeddingService

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.protocols.cache import EmbeddingCacheProtocol

logger = logging.getLogger(__name__)


DEFAULT_MAX_RETRIES = 2
DEFAULT_RETRY_WAIT_MIN = 1.0
DEFAULT_RETRY_WAIT_MAX = 4.0

KNOWN_MODEL_DIMENSIONS: dict[str, int] = {
    # OpenAI
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
    # Voyage AI
    "voyage-3": 1024,
    "voyage-3-lite": 512,
    "voyage-code-3": 1024,
    # Jina AI
    "jina-embeddings-v3": 1024,
    "jina-embeddings-v2-base-en": 768,
    # SiliconFlow
    "BAAI/bge-large-zh-v1.5": 1024,
    "netease-youdao/bce-embedding-base_v1": 768,
    "BAAI/bge-m3": 1024,
    "Pro/BAAI/bge-m3": 1024,
    "Qwen/Qwen3-Embedding-8B": 4096,
    "Qwen/Qwen3-Embedding-4B": 2560,
}


class CloudEmbedding(EmbeddingService):
    """Cloud端 API Embeddingimplements

     via  LiteLLM 统一Call各种Cloud端Embedding API。

    特性：
    - custom api_base 时Auto添加 "openai/" provider Prefix（若模型名 not 含 already 知Prefix）
    - 添加 encoding_format="float" Parameter（OpenAI compatible API 所需）
    - Auto检测 embedding Dimension（首次Call时）
    - optionalCacheSupport（三层Cache：L1 LRU + L2 Redis + L3 API）
    - AutoRetrytemporaryError（网络抖动、Timeout、ConnectionError）

    Args:
        model: 模型名称（LiteLLM Format）
        api_key: API Key（optional）
        api_base: API basic URL（optional）
        cache: Embedding CacheInstance（optional）
        max_retries: MaximumRetry次数（Only对temporaryError）
        retry_wait_min: RetryMinimumWait时间（秒）
        retry_wait_max: RetryMaximumWait时间（秒）

    Example:
        ```python
        from myrm_agent_harness.toolkits.memory._internal.embedding_cache import EmbeddingCache

        cache = EmbeddingCache(...)
        service = CloudEmbedding(
            model="BAAI/bge-m3",
            api_key="sk-xxx",
            api_base="https://api.siliconflow.cn/v1",
            cache=cache,
            max_retries=2
        )
        vectors = await service.embed_batch(["Hello world"])
        single = await service.embed("Hello")
        ```
    """

    def __init__(
        self,
        model: str = "text-embedding-3-small",
        api_key: str | None = None,
        api_base: str | None = None,
        cache: EmbeddingCacheProtocol | None = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_wait_min: float = DEFAULT_RETRY_WAIT_MIN,
        retry_wait_max: float = DEFAULT_RETRY_WAIT_MAX,
    ):
        self._model = model
        self._api_key = api_key
        self._api_base = api_base
        self._cache = cache
        self._max_retries = max_retries
        self._retry_wait_min = retry_wait_min
        self._retry_wait_max = retry_wait_max
        self._dimension: int | None = None

        model_variants: list[str] = [model]
        if "/" in model:
            model_variants.append(model.split("/", 1)[1])
            model_variants.append(model.rsplit("/", 1)[-1])

        for variant in model_variants:
            if variant in KNOWN_MODEL_DIMENSIONS:
                self._dimension = KNOWN_MODEL_DIMENSIONS[variant]
                cache_status = "enabled" if cache is not None else "disabled"
                logger.warning(
                    f" Cloud embedding initialized: {model} | dim={self._dimension} | "
                    f"cache={cache_status} | retries={max_retries}"
                )
                break

        if self._dimension is None:
            cache_status = "enabled" if cache is not None else "disabled"
            logger.warning(
                f" Cloud embedding initialized: {model} | dimension=auto-detect | "
                f"cache={cache_status} | retries={max_retries}"
            )

    @property
    def dimension(self) -> int:
        if self._dimension is None:
            raise RuntimeError(
                f"Embedding dimension not yet determined for model '{self._model}'. "
                "Please call embed() or embed_batch() first to trigger auto-detection."
            )
        return self._dimension

    async def embed(self, text: str) -> list[float]:
        """Embeddingsingletext（带Cache and Retry）

        Args:
            text: inputtext

        Returns:
            EmbeddingVector
        """
        if self._cache is not None:
            cached = await self._cache.get(text)
            if cached is not None:
                return cached

        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(self._max_retries + 1),
            wait=wait_exponential(min=self._retry_wait_min, max=self._retry_wait_max),
            retry=retry_if_exception_type((TimeoutError, ConnectionError, OSError)),
            reraise=True,
        ):
            with attempt:
                results = await self._embed_batch_impl([text])
                vec = results[0] if results else []

        if self._cache is not None and vec:
            await self._cache.put(text, vec)

        return vec

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """批量Embeddingtext（带Cache and Retry）

        对于 not yet 知模型，首次Call时会Auto检测Dimension。

        Args:
            texts: textList

        Returns:
            EmbeddingVectorList
        """
        if not texts:
            return []

        if self._cache is None:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(self._max_retries + 1),
                wait=wait_exponential(min=self._retry_wait_min, max=self._retry_wait_max),
                retry=retry_if_exception_type((TimeoutError, ConnectionError, OSError)),
                reraise=True,
            ):
                with attempt:
                    return await self._embed_batch_impl(texts)

        cached = await self._cache.get_batch(texts)
        miss_indices = [i for i, v in enumerate(cached) if v is None]
        if not miss_indices:
            return [v for v in cached if v is not None]

        miss_texts = [texts[i] for i in miss_indices]

        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(self._max_retries + 1),
            wait=wait_exponential(min=self._retry_wait_min, max=self._retry_wait_max),
            retry=retry_if_exception_type((TimeoutError, ConnectionError, OSError)),
            reraise=True,
        ):
            with attempt:
                new_vecs = await self._embed_batch_impl(miss_texts)

        await self._cache.put_batch(miss_texts, new_vecs)

        result = list(cached)
        for idx, vec in zip(miss_indices, new_vecs, strict=True):
            result[idx] = vec
        return [v for v in result if v is not None]

    async def _embed_batch_impl(self, texts: list[str]) -> list[list[float]]:
        """实际 批量Embeddingimplements（ not 带Cache and Retry）

        Args:
            texts: textList

        Returns:
            EmbeddingVectorList
        """
        if not texts:
            return []

        import time

        try:
            import litellm
        except ImportError as e:
            raise ImportError("litellm is required for CloudEmbedding. Install with: uv add litellm") from e

        model_name = self._model
        if self._api_base and "/" in model_name and not model_name.startswith(("openai/", "azure/", "anthropic/")):
            model_name = f"openai/{model_name}"

        kwargs: dict[str, str | list[str] | None] = {
            "model": model_name,
            "input": [t if t.strip() else " " for t in texts],
            "encoding_format": "float",
        }
        if self._api_key:
            kwargs["api_key"] = self._api_key
        if self._api_base:
            kwargs["api_base"] = self._api_base

        api_start = time.perf_counter()
        response = await litellm.aembedding(**kwargs)
        api_time = (time.perf_counter() - api_start) * 1000

        if self._dimension is None and response.data:
            detected_dim = len(response.data[0]["embedding"])
            self._dimension = detected_dim
            logger.warning(
                f" Auto-detected embedding dimension: {detected_dim} for model '{self._model}'. "
                "This value will be cached for future use."
            )

        logger.debug(
            "Embedding API call completed | Texts: %d | API time: %.2fms | Model: %s",
            len(texts),
            api_time,
            self._model,
        )

        return [item["embedding"] for item in response.data]
