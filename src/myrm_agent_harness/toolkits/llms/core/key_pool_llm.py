"""Key-pool LLM wrapper — transparent API key rotation on errors.

Wraps multiple ``ChatLiteLLM`` instances (same model, different keys)
behind a single ``BaseChatModel`` interface. On rate-limit, auth, or
billing errors the wrapper automatically rotates to the next available
key from the pool while preserving the pool's dispatch strategy.

Layering:  KeyPoolLLM (key rotation) → ManagedLLM (model failover)

[INPUT]
- core.credential_pool::CredentialPool (POS: Framework-level credential scheduling and rotation)
- errors.classifier::ErrorKind, classify_error (POS: LLM error classifier)

[OUTPUT]
- KeyPoolLLM: BaseChatModel with transparent key rotation and strategy-aware observability

[POS]
Framework-level LLM wrapper. Sits below ManagedLLM in the call chain.
Enables high-throughput multi-pane scenarios where a single API key
would hit rate limits or become invalid.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatGenerationChunk, ChatResult

from myrm_agent_harness.toolkits.llms.core.credential_pool import CredentialPool
from myrm_agent_harness.toolkits.llms.errors.classifier import ErrorKind, classify_error, extract_retry_after

logger = logging.getLogger(__name__)


_KEY_ROTATABLE_KINDS = frozenset({
    ErrorKind.RATE_LIMIT,
    ErrorKind.AUTH,
    ErrorKind.BILLING,
})


class KeyPoolLLM(BaseChatModel):
    """BaseChatModel wrapper that rotates API keys on key-specific errors.

    Holds one ``ChatLiteLLM`` instance per key and delegates calls to the
    currently selected instance. When a rate limit, auth failure, or billing
    error is detected, the failing key enters cooldown and the next available
    key is tried automatically.

    Transparent to callers — behaves exactly like a single ``ChatLiteLLM``.
    """

    def __init__(
        self,
        instances: dict[str, BaseChatModel],
        pool: CredentialPool,
    ) -> None:
        super().__init__()
        if not instances:
            raise ValueError("KeyPoolLLM requires at least one LLM instance")
        self._instances = instances
        self._pool = pool
        # Keep a stable reference for bind_tools / property delegation
        self._primary_key = next(iter(instances))
        logger.warning(
            "KeyPoolLLM initialized: %d keys for model %s using %s",
            pool.size,
            getattr(instances[self._primary_key], "model", "unknown"),
            pool.strategy.value,
        )

    @property
    def credential_pool(self) -> CredentialPool:
        return self._pool

    # ------------------------------------------------------------------
    # BaseChatModel interface
    # ------------------------------------------------------------------

    def _report_error(self, key: str, exc: Exception, kind: ErrorKind) -> None:
        """Report an error to the pool, extracting Retry-After when available."""
        retry_after = extract_retry_after(exc) if kind == ErrorKind.RATE_LIMIT else None
        self._pool.report_error(key, kind.value, cooldown_hint_s=retry_after)

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        last_exc: Exception | None = None
        for _attempt in range(self._pool.size):
            key = self._pool.acquire()
            llm = self._instances.get(key)
            if llm is None:
                continue
            try:
                result = await llm._agenerate(messages, stop=stop, run_manager=run_manager, **kwargs)
                self._pool.report_success(key)
                return result
            except Exception as exc:
                kind = classify_error(exc)
                if kind not in _KEY_ROTATABLE_KINDS:
                    raise
                self._report_error(key, exc, kind)
                last_exc = exc
        if last_exc is None:
            raise RuntimeError("KeyPoolLLM failed to locate a credential pool instance")
        raise last_exc

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        last_exc: Exception | None = None
        for _attempt in range(self._pool.size):
            key = self._pool.acquire()
            llm = self._instances.get(key)
            if llm is None:
                continue
            try:
                async for chunk in llm._astream(messages, stop=stop, run_manager=run_manager, **kwargs):
                    yield chunk
                self._pool.report_success(key)
                return
            except Exception as exc:
                kind = classify_error(exc)
                if kind not in _KEY_ROTATABLE_KINDS:
                    raise
                self._report_error(key, exc, kind)
                last_exc = exc
        if last_exc is None:
            raise RuntimeError("KeyPoolLLM failed to locate a credential pool instance")
        raise last_exc

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Sync generation — mirrors the async rotation behavior."""
        last_exc: Exception | None = None
        for _attempt in range(self._pool.size):
            key = self._pool.acquire()
            llm = self._instances.get(key)
            if llm is None:
                continue
            try:
                result = llm._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
                self._pool.report_success(key)
                return result
            except Exception as exc:
                kind = classify_error(exc)
                if kind not in _KEY_ROTATABLE_KINDS:
                    raise
                self._report_error(key, exc, kind)
                last_exc = exc
        if last_exc is None:
            raise RuntimeError("KeyPoolLLM failed to locate a credential pool instance")
        raise last_exc

    def bind_tools(self, tools: Any, **kwargs: Any) -> KeyPoolLLM:
        """Bind tools on all underlying LLM instances, preserving key rotation.

        Unlike the naive approach of delegating to the primary instance (which
        returns a new ``ChatLiteLLM`` that loses rotation capability), this
        binds tools on every pooled instance and returns ``self`` so that all
        subsequent calls continue to rotate keys transparently.
        """
        for instance in self._instances.values():
            instance.bind_tools(tools, **kwargs)
        return self

    @property
    def _llm_type(self) -> str:
        return "key_pool_llm"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        primary = self._instances[self._primary_key]
        return {
            "model": getattr(primary, "model", "unknown"),
            "pool_size": self._pool.size,
            "pool_strategy": self._pool.strategy.value,
        }
