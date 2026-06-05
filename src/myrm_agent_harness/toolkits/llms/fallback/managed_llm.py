"""Managed LLM wrapper with ModelFallbackManager integration.

[INPUT]
- langchain_core.language_models.BaseChatModel (POS: LangChain LLM base class)
- .manager.ModelFallbackManager (POS: Fallback manager with cooldown and probing)

[OUTPUT]
- ManagedLLM: LLM wrapper that internally uses ModelFallbackManager

[POS]
LLM wrapper that transparently integrates ModelFallbackManager into LangChain's
LLM call chain. Enables automatic failover with cooldown, probing, and scenario-aware
selection without modifying LangGraph agent code.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatGenerationChunk, ChatResult

from .config import ProbeConfig
from .events import FailoverCallback, RecoveryCallback
from .manager import ModelFallbackManager
from .scenario import ScenarioType

logger = logging.getLogger(__name__)


@dataclass
class FallbackModel:
    """Fallback model configuration.

    Attributes:
        llm: LLM instance
        name: Model name (for logging and metrics)
        cost: Relative cost (0.0-1.0, lower is better)
        latency: Relative latency (0.0-1.0, lower is better)
        quality: Relative quality (0.0-1.0, higher is better)
    """

    llm: BaseChatModel
    name: str
    cost: float = 0.5
    latency: float = 0.5
    quality: float = 0.8


class ManagedLLM(BaseChatModel):
    """LLM wrapper with integrated ModelFallbackManager.

    Transparently wraps multiple LLM instances with automatic failover,
    cooldown periods, and probing. Compatible with LangChain and LangGraph.

    Examples:
        # 2-level fallback (backward compatible)
        managed_llm = ManagedLLM(
            main_llm=gpt4_instance,
            fallback_llm=claude_instance,
            main_model_name="gpt-4",
            fallback_model_name="claude-3-opus",
        )

        # Multi-level fallback (3+ models)
        managed_llm = ManagedLLM(
            main_llm=gpt4_instance,
            fallback_models=[
                FallbackModel(llm=gpt4_turbo, name="gpt-4-turbo", cost=0.3, quality=0.75),
                FallbackModel(llm=gpt4o_mini, name="gpt-4o-mini", cost=0.1, quality=0.6),
            ],
        )

        # Use like any LangChain LLM
        result = await managed_llm.ainvoke(messages)
    """

    def __init__(
        self,
        main_llm: BaseChatModel,
        fallback_llm: BaseChatModel | None = None,
        fallback_models: list[FallbackModel] | None = None,
        main_model_name: str = "main",
        fallback_model_name: str = "fallback",
        main_cost: float = 0.5,
        main_latency: float = 0.5,
        main_quality: float = 0.8,
        fallback_cost: float = 0.3,
        fallback_latency: float = 0.4,
        fallback_quality: float = 0.7,
        scenario: ScenarioType = ScenarioType.BALANCED,
        probe_config: ProbeConfig | None = None,
        on_failover: FailoverCallback | None = None,
        on_recovery: RecoveryCallback | None = None,
    ) -> None:
        """Initialize ManagedLLM.

        Args:
            main_llm: Primary LLM instance
            fallback_llm: Single fallback LLM (backward compatible, mutually exclusive with fallback_models)
            fallback_models: List of fallback models for multi-level fallback (mutually exclusive with fallback_llm)
            main_model_name: Name for main model (for logging)
            fallback_model_name: Name for fallback model (used only if fallback_llm is provided)
            main_cost: Relative cost of main model (0.0-1.0, lower is better)
            main_latency: Relative latency of main model (0.0-1.0, lower is better)
            main_quality: Relative quality of main model (0.0-1.0, higher is better)
            fallback_cost: Relative cost of fallback model (used only if fallback_llm is provided)
            fallback_latency: Relative latency of fallback model (used only if fallback_llm is provided)
            fallback_quality: Relative quality of fallback model (used only if fallback_llm is provided)
            scenario: Usage scenario for model selection
            probe_config: Optional probe and cooldown configuration (uses defaults if None)
            on_failover: Optional callback function called when failover occurs
            on_recovery: Optional callback function called when model recovers

        Raises:
            ValueError: If both fallback_llm and fallback_models are provided
        """
        super().__init__()

        # Validate mutually exclusive parameters
        if fallback_llm is not None and fallback_models is not None:
            raise ValueError("Cannot specify both fallback_llm and fallback_models")

        self._main_llm = main_llm
        self._main_model_name = main_model_name
        self._scenario = scenario
        self._probe_config = probe_config
        self._on_failover = on_failover
        self._on_recovery = on_recovery

        # Store all LLMs for call_fn closures
        self._llms: dict[str, BaseChatModel] = {"main": main_llm}

        # Current invocation context (set during ainvoke)
        self._current_messages: list[BaseMessage] | None = None
        self._current_kwargs: dict[str, Any] | None = None

        # Create fallback manager
        self._manager = ModelFallbackManager[ChatResult](
            probe_config=probe_config,
            on_failover=on_failover,
            on_recovery=on_recovery,
        )

        # Add main model
        self._manager.add_candidate(
            name=main_model_name,
            priority=0,
            call_fn=self._create_call_fn("main"),
            llm_instance=main_llm,
            cost=main_cost,
            latency=main_latency,
            quality=main_quality,
        )

        # Add fallback models
        if fallback_models is not None:
            # Multi-level fallback mode
            for i, fb_model in enumerate(fallback_models):
                self._llms[fb_model.name] = fb_model.llm
                self._manager.add_candidate(
                    name=fb_model.name,
                    priority=i + 1,
                    call_fn=self._create_call_fn(fb_model.name),
                    llm_instance=fb_model.llm,
                    cost=fb_model.cost,
                    latency=fb_model.latency,
                    quality=fb_model.quality,
                )

            fallback_names = [fb.name for fb in fallback_models]
            logger.info(
                f"ManagedLLM initialized: main={main_model_name}, fallbacks={fallback_names}, scenario={scenario.value}"
            )
        elif fallback_llm is not None:
            # Backward compatible 2-level mode
            self._llms[fallback_model_name] = fallback_llm
            self._manager.add_candidate(
                name=fallback_model_name,
                priority=1,
                call_fn=self._create_call_fn(fallback_model_name),
                llm_instance=fallback_llm,
                cost=fallback_cost,
                latency=fallback_latency,
                quality=fallback_quality,
            )
            logger.info(
                f"ManagedLLM initialized: main={main_model_name}, "
                f"fallback={fallback_model_name}, scenario={scenario.value}"
            )
        else:
            logger.info(f"ManagedLLM initialized: main={main_model_name} (no fallback)")

    def _create_call_fn(self, model_key: str):
        """Create a call function for the specified model.

        Args:
            model_key: Key in self._llms dict

        Returns:
            Async function that calls the LLM with current context
        """

        async def call_fn() -> ChatResult:
            llm = self._llms[model_key]
            assert self._current_messages is not None
            assert self._current_kwargs is not None
            return await llm.agenerate([self._current_messages], **self._current_kwargs)

        return call_fn

    async def _call_main(self) -> ChatResult:
        """Call main LLM with current context."""
        assert self._current_messages is not None
        assert self._current_kwargs is not None
        return await self._main_llm.agenerate([self._current_messages], **self._current_kwargs)

    async def _call_fallback(self) -> ChatResult:
        """Call fallback LLM with current context."""
        llm = self._llms.get("fallback") or self._llms.get(list(self._llms.keys())[1])
        assert llm is not None
        assert self._current_messages is not None
        assert self._current_kwargs is not None
        return await llm.agenerate([self._current_messages], **self._current_kwargs)

    async def _run_preflight_guard(self, messages: list[BaseMessage], **kwargs: Any) -> None:
        """Zero-cost preflight check to prevent 400 Context Exceeded errors.

        Estimates the total token count of the messages locally. If it exceeds
        the model's maximum context limit (minus a 2% safety buffer), immediately
        raises a Context Overflow error, completely avoiding the network request.
        """
        try:
            import asyncio
            import json

            from myrm_agent_harness.toolkits.llms.errors import MyrmLLMError
            from myrm_agent_harness.toolkits.llms.errors.error_types import FailoverReason
            from myrm_agent_harness.toolkits.llms.utils.model_utils import get_model_context_limit
            from myrm_agent_harness.utils.text_utils import get_token_count
            from myrm_agent_harness.utils.token_estimation import estimate_messages_tokens

            limit = get_model_context_limit(self._main_llm) or 128000

            # Extract requested output tokens (default to 4096 if not specified)
            requested_max_tokens = kwargs.get("max_tokens") or 4096

            # Allow 2% headroom for tokenizer variance and strictly reserve output tokens
            threshold = int((limit - requested_max_tokens) * 0.98)

            def _estimate_all_tokens() -> int:
                total = estimate_messages_tokens(messages)

                # Add tokens from bound tools if present in kwargs
                tools = kwargs.get("tools")
                if tools:
                    try:
                        # Try to dump tools to json string to estimate
                        tools_str = json.dumps(tools, default=str)
                        total += get_token_count(tools_str)
                    except Exception as e:
                        logger.debug(f"Failed to estimate tools tokens: {e}")

                return total

            # Run in a separate thread to prevent blocking the event loop on huge contexts
            tokens = await asyncio.to_thread(_estimate_all_tokens)

            if tokens > threshold:
                logger.warning(
                    f" Preflight Guard Blocked: Estimated tokens {tokens} > threshold {threshold} (limit: {limit})"
                )
                raise MyrmLLMError(
                    error_code=FailoverReason.CONTEXT_OVERFLOW,
                    default_msg=f"Context length exceeded (Preflight Guard): {tokens} > {threshold}",
                )
        except MyrmLLMError:
            raise
        except Exception as e:
            logger.debug(f"Preflight guard failed to run, bypassing: {e}")

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Internal generation method called by LangChain."""
        await self._run_preflight_guard(messages, **kwargs)

        # Set current context for call_fn closures
        self._current_messages = messages
        self._current_kwargs = {"stop": stop, "run_manager": run_manager, **kwargs}

        try:
            # Use manager to execute with automatic failover
            result = await self._manager.execute(scenario=self._scenario)
            return result
        finally:
            # Clear context
            self._current_messages = None
            self._current_kwargs = None

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        """Delegate streaming to the primary underlying LLM.

        Failover between models is handled at the stream_executor level
        (which catches errors and rebuilds the agent graph with a new LLM),
        so here we simply stream from the current main LLM.
        """
        await self._run_preflight_guard(messages, **kwargs)
        async for chunk in self._main_llm._astream(messages, stop=stop, run_manager=run_manager, **kwargs):
            yield chunk

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Synchronous generation (not supported, use async)."""
        raise NotImplementedError("ManagedLLM only supports async operation. Use ainvoke() instead.")

    def bind_tools(
        self,
        tools: Any,
        **kwargs: Any,
    ) -> Any:
        """Delegate tool binding to the main LLM."""
        return self._main_llm.bind_tools(tools, **kwargs)

    @property
    def _llm_type(self) -> str:
        """Return LLM type identifier."""
        return "managed_llm"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        """Return identifying parameters."""
        fallback_names = [name for name in self._llms if name != "main"]
        return {
            "main_model": self._main_model_name,
            "fallback_models": fallback_names if fallback_names else None,
            "scenario": self._scenario.value,
        }
