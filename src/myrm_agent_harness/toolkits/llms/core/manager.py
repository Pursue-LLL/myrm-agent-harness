"""LLM Manager with caching and credential pool support.


[INPUT]
- core.llm::ChatLiteLLM, create_litellm_model (POS: LiteLLM wrapper and factory function)
- core.credential_pool::CredentialPool (POS: framework-level credential scheduling and rotation)
- core.credential_pool::CredentialPoolStrategy (POS: strategy enum for key dispatch)
- core.credential_pool::normalize_api_keys (POS: order-preserving API key normalization utility)
- core.key_pool_llm::KeyPoolLLM (POS: key-rotation LLM wrapper)
- utils.lru_cache::LRUCache (POS: LRU cache implementation)
- hashlib::hashlib (POS: Python hash library for cache key generation)

[OUTPUT]
- LLMManager: LLM manager class (provides strategy-aware LLM instance caching and management)

[POS]
LLM manager. Provides efficient LLM instance management with LRU caching for improved performance
and resource utilization. Only caches successfully created and connected instances; supports
model-parameter-based cache key generation and automatic cache management.
Supports multi-API-key rotation: when multiple keys are provided, automatically creates KeyPoolLLM
for rate-limit-aware key rotation. Used by the business layer as a management abstraction to simplify
LLM instance creation and reuse. Pooled cache identity is strategy-aware and respects key order.
"""

from __future__ import annotations

import hashlib
import logging
from typing import TYPE_CHECKING, Any

from langchain_core.language_models import BaseChatModel

from myrm_agent_harness.toolkits.llms.core.credential_pool import (
    CredentialPool,
    CredentialPoolStrategy,
    normalize_api_keys,
)
from myrm_agent_harness.toolkits.llms.core.key_pool_llm import KeyPoolLLM
from myrm_agent_harness.toolkits.llms.core.llm import ChatLiteLLM, create_litellm_model
from myrm_agent_harness.utils.lru_cache import LRUCache

if TYPE_CHECKING:
    from pydantic import BaseModel

logger = logging.getLogger(__name__)


class LLMManager:
    """LLM Manager with instance caching and credential pool support.

    Provides efficient LLM instance management with LRU caching.
    When multiple API keys are provided, creates a ``KeyPoolLLM``
    that automatically rotates keys on rate-limit, auth, or billing
    errors using the configured credential pool strategy.

    Features:
    - LRU caching (configurable size, default 32)
    - Cache key generation based on model parameters
    - Multi-key credential pool with strategy-aware error rotation
    - Automatic cache management
    """

    _llm_cache: LRUCache[BaseChatModel] = LRUCache(maxsize=32, id="llm_cache")

    @classmethod
    async def get_llm(
        cls,
        model: str,
        api_key: str,
        base_url: str | None = None,
        temperature: float | None = None,
        streaming: bool = False,
        *,
        api_keys: list[str] | None = None,
        credential_pool_strategy: CredentialPoolStrategy | str | None = None,
        **kwargs: Any,
    ) -> BaseChatModel:
        """Get or create an LLM instance with caching.

        When ``api_keys`` contains multiple keys, returns a ``KeyPoolLLM``
        that transparently rotates keys on rate-limit errors.

        Args:
            model: Model name (e.g., "gpt-4", "claude-3-opus")
            api_key: Primary API key for authentication
            base_url: Optional custom API base URL
            temperature: Temperature parameter (default 0.2)
            streaming: Whether to enable streaming (default False)
            api_keys: Optional list of API keys for credential pooling.
                      When provided with >1 key, creates a KeyPoolLLM.
            credential_pool_strategy: Optional dispatch strategy for pooled
                credentials. Uses the environment default when omitted.
            **kwargs: Additional parameters passed to create_litellm_model

        Returns:
            BaseChatModel: LLM instance (ChatLiteLLM or KeyPoolLLM)
        """
        normalized_keys = normalize_api_keys(api_keys) if api_keys else None
        effective_keys = normalized_keys if normalized_keys and len(normalized_keys) > 1 else None

        if effective_keys:
            return cls._get_pooled_llm(
                model=model,
                api_keys=effective_keys,
                base_url=base_url,
                temperature=temperature,
                streaming=streaming,
                credential_pool_strategy=credential_pool_strategy,
                **kwargs,
            )

        return cls._get_single_llm(
            model=model,
            api_key=api_key,
            base_url=base_url,
            temperature=temperature,
            streaming=streaming,
            **kwargs,
        )

    @classmethod
    def _get_single_llm(
        cls,
        model: str,
        api_key: str,
        base_url: str | None,
        temperature: float | None,
        streaming: bool,
        **kwargs: Any,
    ) -> ChatLiteLLM:
        """Create or retrieve a single-key LLM instance."""
        api_key_hash = hashlib.blake2b(api_key.encode(), digest_size=8).hexdigest()
        cache_data = f"{model}_{temperature}_{base_url or ''}_{api_key_hash}_{streaming}"
        if kwargs:
            kwargs_str = "_".join(f"{k}:{v}" for k, v in sorted(kwargs.items()))
            cache_data += f"_{kwargs_str}"

        cache_key = hashlib.blake2b(cache_data.encode(), digest_size=16).hexdigest()

        cached_llm = cls._llm_cache.get(cache_key)
        if isinstance(cached_llm, ChatLiteLLM):
            return cached_llm

        llm = create_litellm_model(
            model=model,
            base_url=base_url,
            api_key=api_key,
            temperature=temperature,
            streaming=streaming,
            **kwargs,
        )
        cls._llm_cache.set(cache_key, llm)
        return llm

    @classmethod
    def _get_pooled_llm(
        cls,
        model: str,
        api_keys: list[str],
        base_url: str | None,
        temperature: float | None,
        streaming: bool,
        credential_pool_strategy: CredentialPoolStrategy | str | None = None,
        **kwargs: Any,
    ) -> KeyPoolLLM:
        """Create or retrieve a multi-key pooled LLM instance."""
        normalized_keys = normalize_api_keys(api_keys)
        resolved_strategy = CredentialPoolStrategy.resolve(credential_pool_strategy)
        key_hashes = [hashlib.blake2b(k.encode(), digest_size=8).hexdigest() for k in normalized_keys]
        pool_hash = hashlib.blake2b("|".join(key_hashes).encode(), digest_size=8).hexdigest()
        cache_data = f"pool_{model}_{temperature}_{base_url or ''}_{resolved_strategy.value}_{pool_hash}_{streaming}"
        if kwargs:
            kwargs_str = "_".join(f"{k}:{v}" for k, v in sorted(kwargs.items()))
            cache_data += f"_{kwargs_str}"
        cache_key = hashlib.blake2b(cache_data.encode(), digest_size=16).hexdigest()

        cached = cls._llm_cache.get(cache_key)
        if isinstance(cached, KeyPoolLLM):
            return cached

        instances: dict[str, BaseChatModel] = {}
        for key in normalized_keys:
            instances[key] = create_litellm_model(
                model=model,
                base_url=base_url,
                api_key=key,
                temperature=temperature,
                streaming=streaming,
                **kwargs,
            )

        pool = CredentialPool(normalized_keys, strategy=resolved_strategy)
        pooled = KeyPoolLLM(instances=instances, pool=pool)
        cls._llm_cache.set(cache_key, pooled)
        logger.warning(
            "Created KeyPoolLLM for %s with %d keys using %s",
            model,
            len(normalized_keys),
            resolved_strategy.value,
        )
        return pooled

    @classmethod
    async def get_llm_from_config(
        cls,
        config: BaseModel,
        streaming: bool = True,
        *,
        api_keys: list[str] | None = None,
        credential_pool_strategy: CredentialPoolStrategy | str | None = None,
    ) -> BaseChatModel:
        """Create LLM instance from configuration object.

        Args:
            config: Configuration object with model, api_key, base_url, model_kwargs
            streaming: Whether to enable streaming (default True)
            api_keys: Optional list of API keys for credential pooling
            credential_pool_strategy: Optional dispatch strategy for pooled keys

        Returns:
            BaseChatModel: LLM instance (ChatLiteLLM or KeyPoolLLM)
        """
        model_kwargs = getattr(config, "model_kwargs", None) or {}
        effective_api_keys = api_keys if api_keys is not None else getattr(config, "api_keys", None)
        effective_strategy = (
            credential_pool_strategy
            if credential_pool_strategy is not None
            else getattr(config, "credential_pool_strategy", None)
        )

        return await cls.get_llm(
            model=config.model,  # type: ignore
            api_key=config.api_key,  # type: ignore
            base_url=getattr(config, "base_url", None),
            streaming=streaming,
            api_keys=effective_api_keys,
            credential_pool_strategy=effective_strategy,
            **model_kwargs,
        )

    @classmethod
    def clear_cache(cls) -> None:
        """Clear all cached LLM instances

        Useful for testing or when you want to force recreation of all instances.

        Example:
            >>> LLMManager.clear_cache()
        """
        cls._llm_cache.clear()
        logger.warning("LLM cache cleared")

    @classmethod
    def get_cache_size(cls) -> int:
        """Get current cache size

        Returns:
            Number of cached LLM instances

        Example:
            >>> size = LLMManager.get_cache_size()
            >>> print(f"Cached instances: {size}")
        """
        return len(cls._llm_cache)


# Create global LLM manager instance for convenience
llm_manager = LLMManager()
