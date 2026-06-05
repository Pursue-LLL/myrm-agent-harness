"""Privacy-aware model routing — dynamic LLM selection based on PII sensitivity.

Wraps a cloud model and an optional local model behind a single BaseChatModel
interface. On each LLM call, reads the current turn's sensitivity level from
``PrivacyTracker`` (ContextVar, set by SecurityGuardrailMiddleware.before_model)
and routes to the appropriate backend:

  S1 → cloud model
  S2 → cloud (after redaction) or local, per ``s2_strategy``
  S3 → local model (data never leaves the machine)

Timeline safety: ``before_model`` detects and redacts PII *before* this model's
``_agenerate``/``_astream`` is called, so the routing decision always sees the
latest sensitivity level and messages are already sanitized when needed.

[INPUT]
- agent.security.types::PrivacyRoutingConfig, (POS: Foundation layer of the security type hierarchy. All other security modules import from here; this module imports from none of them.)
- agent.security.guards.privacy_tracker::get_privacy_tracker (POS: Per-Turn  ContextVar session-scoped TurnLevel)
- agent.security.audit::record_decision (POS: Cross-cutting concern. Called from tool_interceptor_middleware and all security guard modules at every decision point.)
- utils.runtime.progress_sink::get_tool_progress_sink (POS: ContextVar  Agent SSE  BaseAgent)

[OUTPUT]
- PrivacyRoutingModel: BaseChatModel wrapper with privacy-aware routing

[POS]
LLM routing layer. Sits between the Agent and actual LLM backends, providing
transparent privacy-based model selection. Zero-intrusion to Agent, Middleware,
and StreamExecutor — they see a normal BaseChatModel.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Iterator, Sequence
from typing import Any

from langchain_core.callbacks import (
    AsyncCallbackManagerForLLMRun,
    CallbackManagerForLLMRun,
)
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatGenerationChunk, ChatResult
from langchain_core.tools import BaseTool

from myrm_agent_harness.core.security.types import (
    PrivacyRoutingConfig,
    SensitivityLevel,
)

logger = logging.getLogger(__name__)

_ROUTING_RETRY_COUNT = 1


class PrivacyRoutingModel(BaseChatModel):
    """BaseChatModel wrapper that routes to cloud or local model based on privacy level.

    When ``local_llm`` is None, all requests pass through to ``cloud_llm``
    (transparent mode — zero overhead).
    """

    cloud_llm: BaseChatModel
    local_llm: BaseChatModel | None = None
    routing_config: PrivacyRoutingConfig = PrivacyRoutingConfig()

    @property
    def _llm_type(self) -> str:
        return "privacy-routing"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        return {
            "cloud_model": self.cloud_llm._llm_type,
            "local_model": self.local_llm._llm_type if self.local_llm else None,
            "routing_config": {
                "s2_strategy": self.routing_config.s2_strategy,
                "s3_strategy": self.routing_config.s3_strategy,
                "local_fallback": self.routing_config.local_fallback,
            },
        }

    def bind_tools(
        self,
        tools: Sequence[dict[str, Any] | type | BaseTool | Any],
        **kwargs: Any,
    ) -> BaseChatModel:
        """Bind tools to both underlying models so either can handle tool calls."""
        bound = self.model_copy()
        bound.cloud_llm = self.cloud_llm.bind_tools(tools, **kwargs)  # type: ignore[assignment]
        if self.local_llm is not None:
            try:
                bound.local_llm = self.local_llm.bind_tools(tools, **kwargs)  # type: ignore[assignment]
            except Exception:
                logger.debug("Local model does not support bind_tools, using unbound")
        return bound  # type: ignore[return-value]

    def _resolve_target(self) -> tuple[BaseChatModel, str]:
        """Determine which model to route to based on current privacy level.

        Returns (target_model, route_label) for logging and audit.
        """
        from myrm_agent_harness.core.security.guards.privacy_tracker import (
            get_privacy_tracker,
        )

        if self.local_llm is None:
            return self.cloud_llm, "cloud(no_local_configured)"

        tracker = get_privacy_tracker()
        level = tracker.current_turn_level
        cfg = self.routing_config

        if level == SensitivityLevel.S3:
            if cfg.s3_strategy == "block":
                return self.cloud_llm, "cloud(s3_block_handled_by_middleware)"
            return self.local_llm, "local(s3_forced)"

        if level == SensitivityLevel.S2:
            if cfg.s2_strategy == "local":
                return self.local_llm, "local(s2_local)"
            return self.cloud_llm, "cloud(s2_after_redact)"

        return self.cloud_llm, "cloud(s1_safe)"

    def _handle_local_failure(self, exc: Exception) -> BaseChatModel:
        """Handle local model failure according to fallback strategy.

        Raises RuntimeError if fallback is 'block'.
        Returns cloud_llm if fallback is 'force_redact_cloud'.
        """
        cfg = self.routing_config
        if cfg.local_fallback == "force_redact_cloud":
            logger.warning(
                "[PRIVACY-ROUTING] Local model failed (%s), falling back to cloud with forced redaction",
                type(exc).__name__,
            )
            self._verify_redaction_safety()
            return self.cloud_llm
        raise RuntimeError(f"Local model unavailable and fallback is 'block': {exc}") from exc

    def _verify_redaction_safety(self) -> None:
        """Double-check that messages have been properly redacted before cloud fallback.

        If PII is still detected after redaction, escalate to S3 and block.
        """
        from myrm_agent_harness.core.security.guards.privacy_tracker import (
            get_privacy_tracker,
        )

        tracker = get_privacy_tracker()
        if tracker.current_turn_level == SensitivityLevel.S3:
            raise RuntimeError(
                "Cannot fall back to cloud: S3 content detected. Local model is required for confidential data."
            )

    def _record_routing_decision(self, route_label: str) -> None:
        """Record routing decision for audit and notify PrivacyTracker for SSE."""
        try:
            from myrm_agent_harness.core.security.audit import record_decision

            record_decision("model_routing", "PRIVACY_ROUTE", route_label)
        except Exception:
            pass

        try:
            from myrm_agent_harness.core.security.guards.privacy_tracker import (
                get_privacy_tracker,
            )

            get_privacy_tracker().record_route(route_label)
        except Exception:
            pass

    def _get_target_and_kwargs(self, target: Any, kwargs: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
        target_kwargs = kwargs.copy()
        actual_target = target
        logger.warning(f"DEBUG _get_target_and_kwargs: initial target type: {type(target)}")
        while hasattr(actual_target, "bound"):
            if hasattr(actual_target, "kwargs"):
                target_kwargs.update(actual_target.kwargs)
            actual_target = actual_target.bound
        logger.warning(
            f"DEBUG _get_target_and_kwargs: final target type: {type(actual_target)}, target_kwargs keys: {list(target_kwargs.keys())}"
        )
        return actual_target, target_kwargs

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        target, route_label = self._resolve_target()
        self._record_routing_decision(route_label)
        logger.info("[PRIVACY-ROUTING] %s", route_label)

        if target is self.local_llm:
            for attempt in range(_ROUTING_RETRY_COUNT + 1):
                try:
                    actual_target, target_kwargs = self._get_target_and_kwargs(target, kwargs)
                    return actual_target._generate(messages, stop=stop, run_manager=run_manager, **target_kwargs)
                except Exception as exc:
                    if attempt < _ROUTING_RETRY_COUNT:
                        logger.warning(
                            "[PRIVACY-ROUTING] Local model attempt %d failed, retrying",
                            attempt + 1,
                        )
                        continue
                    target = self._handle_local_failure(exc)
                    actual_target, target_kwargs = self._get_target_and_kwargs(target, kwargs)
                    return actual_target._generate(messages, stop=stop, run_manager=run_manager, **target_kwargs)

        actual_target, target_kwargs = self._get_target_and_kwargs(target, kwargs)
        return actual_target._generate(messages, stop=stop, run_manager=run_manager, **target_kwargs)

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        target, route_label = self._resolve_target()
        self._record_routing_decision(route_label)
        logger.info("[PRIVACY-ROUTING] %s", route_label)

        if target is self.local_llm:
            for attempt in range(_ROUTING_RETRY_COUNT + 1):
                try:
                    actual_target, target_kwargs = self._get_target_and_kwargs(target, kwargs)
                    return await actual_target._agenerate(messages, stop=stop, run_manager=run_manager, **target_kwargs)
                except Exception as exc:
                    if attempt < _ROUTING_RETRY_COUNT:
                        logger.warning(
                            "[PRIVACY-ROUTING] Local model attempt %d failed, retrying",
                            attempt + 1,
                        )
                        continue
                    target = self._handle_local_failure(exc)
                    actual_target, target_kwargs = self._get_target_and_kwargs(target, kwargs)
                    return await actual_target._agenerate(messages, stop=stop, run_manager=run_manager, **target_kwargs)

        actual_target, target_kwargs = self._get_target_and_kwargs(target, kwargs)
        return await actual_target._agenerate(messages, stop=stop, run_manager=run_manager, **target_kwargs)

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        target, route_label = self._resolve_target()
        self._record_routing_decision(route_label)
        logger.info("[PRIVACY-ROUTING] streaming via %s", route_label)

        if target is self.local_llm:
            try:
                actual_target, target_kwargs = self._get_target_and_kwargs(target, kwargs)
                yield from actual_target._stream(messages, stop=stop, run_manager=run_manager, **target_kwargs)
                return
            except Exception as exc:
                target = self._handle_local_failure(exc)

        actual_target, target_kwargs = self._get_target_and_kwargs(target, kwargs)
        yield from actual_target._stream(messages, stop=stop, run_manager=run_manager, **target_kwargs)

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        target, route_label = self._resolve_target()
        self._record_routing_decision(route_label)
        logger.info("[PRIVACY-ROUTING] async streaming via %s", route_label)

        if target is self.local_llm:
            try:
                actual_target, target_kwargs = self._get_target_and_kwargs(target, kwargs)
                async for chunk in actual_target._astream(
                    messages, stop=stop, run_manager=run_manager, **target_kwargs
                ):
                    yield chunk
                return
            except Exception as exc:
                target = self._handle_local_failure(exc)

        actual_target, target_kwargs = self._get_target_and_kwargs(target, kwargs)
        async for chunk in actual_target._astream(messages, stop=stop, run_manager=run_manager, **target_kwargs):
            yield chunk
