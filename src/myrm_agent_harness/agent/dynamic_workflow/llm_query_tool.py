"""DW PTC tools — LlmQueryTool and LlmQueryBatchedTool for Dynamic Workflows.

[INPUT]
- agent.base_agent::BaseAgent (POS: Parent agent providing llm / model_resolver)
- agent.sub_agents.builder::resolve_llm (POS: 4-level model resolution chain)
- agent.sub_agents.types::SubagentConfig (POS: Model routing carrier)
- utils.token_economics.tracker::record_token_usage, record_token_error (POS: Token/cost bookkeeping)
- utils.token_economics.cost_engine::compute_cost_by_tokens (POS: Token-count cost estimation)
- utils.runtime.cancellation::CancellationToken

[OUTPUT]
- LlmQueryTool: PTC tool exposed as myrm_tools.llm_query — single lightweight LLM sub-call
- LlmQueryBatchedTool: PTC tool exposed as myrm_tools.llm_query_batched — concurrent, order-preserving batch sub-calls
- _MAX_BATCH_QUERIES: Hard cap on prompts per batched call
- _MAX_BATCH_CONCURRENCY: Default concurrency bound for batched calls

[POS]
Bridges the PTC Python script to direct LLM calls without spawning a sub-agent.
Suitable for cheap, focused sub-tasks (extraction, classification, summarization,
fact-checking a chunk of text) where a full sub-agent loop would be wasteful.
Every call is recorded via the shared token tracker and honors cancellation.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

from myrm_agent_harness.utils.token_economics.cost_engine import (
    compute_cost_by_tokens,
)
from myrm_agent_harness.utils.token_economics.tracker import (
    record_token_error,
    record_token_usage,
)

logger = logging.getLogger(__name__)

_MAX_BATCH_QUERIES = 200
_MAX_BATCH_CONCURRENCY = 10


class LlmQueryInput(BaseModel):
    prompt: str = Field(
        ...,
        description="The instruction or question to send to the LLM.",
    )
    system: str | None = Field(
        default=None,
        description="Optional system prompt. Helps ground the model when "
        "processing a chunk of text or enforcing an output format.",
    )
    model: str | None = Field(
        default=None,
        description="Optional model override (e.g. 'openai/gpt-4o-mini'). "
        "Defaults to the light tier of the current agent when available.",
    )
    max_tokens: int | None = Field(
        default=None,
        ge=1,
        le=8192,
        description="Optional cap on output tokens. Defaults to 2048.",
    )
    temperature: float | None = Field(
        default=None,
        ge=0.0,
        le=2.0,
        description="Optional sampling temperature. Defaults to the model default.",
    )


class LlmQueryBatchedInput(BaseModel):
    prompts: list[str] = Field(
        ...,
        description="List of prompts to process in parallel. Results preserve input order.",
    )
    system: str | None = Field(
        default=None,
        description="Optional shared system prompt applied to every prompt.",
    )
    model: str | None = Field(
        default=None,
        description="Optional model override shared by all prompts.",
    )
    max_tokens: int | None = Field(
        default=None,
        ge=1,
        le=8192,
        description="Optional cap on output tokens for each prompt.",
    )
    temperature: float | None = Field(
        default=None,
        ge=0.0,
        le=2.0,
        description="Optional sampling temperature for all prompts.",
    )
    max_concurrent: int = Field(
        default=5,
        ge=1,
        le=_MAX_BATCH_CONCURRENCY,
        description="Max concurrent LLM calls. Bounded by the workflow hard cap.",
    )


def _extract_model_name(llm: object) -> str | None:
    """Best-effort extraction of the resolved model name for cost accounting."""
    for attr in ("model_name", "model", "model_id", "deployment_name"):
        value = getattr(llm, attr, None)
        if isinstance(value, str) and value:
            return value
    return None


def _build_messages(prompt: str, system: str | None) -> list[HumanMessage | SystemMessage]:
    messages: list[HumanMessage | SystemMessage] = []
    if system:
        messages.append(SystemMessage(content=system))
    messages.append(HumanMessage(content=prompt))
    return messages


class LlmQueryTool(BaseTool):
    """PTC tool that performs a single lightweight LLM sub-call without spawning a sub-agent."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str = "llm_query"
    description: str = (
        "Call the LLM directly with a single prompt. Returns the model's text answer "
        "without spawning a sub-agent — cheap and fast for focused sub-tasks such as "
        "extraction, classification, summarization, or answering a question over a chunk of text. "
        "For many independent prompts, prefer llm_query_batched (same work, far fewer calls)."
    )
    args_schema: type[BaseModel] = LlmQueryInput

    parent_agent: object
    cancel_token: object | None = None

    def _run(
        self,
        prompt: str,
        system: str | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> object:
        raise NotImplementedError("LlmQueryTool only supports async execution.")

    async def _arun(
        self,
        prompt: str,
        system: str | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> object:
        return await self._query_one(
            prompt=prompt,
            system=system,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
        )

    async def _resolve_llm(self, model: str | None) -> object:
        """Resolve an LLM via the shared 4-level chain, defaulting to the light tier."""
        from myrm_agent_harness.agent.sub_agents.builder import resolve_llm
        from myrm_agent_harness.agent.sub_agents.types import SubagentConfig

        resolver = getattr(self.parent_agent, "model_resolver", None)
        config = SubagentConfig(
            system_prompt="",
            max_spawn_depth=0,
            model=model or "",
            model_resolver=resolver,
        )
        return await resolve_llm(
            config=config,
            parent_agent=self.parent_agent,
            complexity_tier="simple",
        )

    async def _query_one(
        self,
        *,
        prompt: str,
        system: str | None,
        model: str | None,
        max_tokens: int | None,
        temperature: float | None,
    ) -> dict[str, object]:
        if self.cancel_token is not None and getattr(self.cancel_token, "is_cancelled", False):
            return {"success": False, "error": "Workflow cancelled by user."}

        llm = await self._resolve_llm(model)
        model_name = _extract_model_name(llm)
        messages = _build_messages(prompt, system)

        invoke_kwargs: dict[str, Any] = {}
        if max_tokens is not None:
            invoke_kwargs["max_tokens"] = max_tokens
        if temperature is not None:
            invoke_kwargs["temperature"] = temperature

        started = time.perf_counter()
        try:
            response = await llm.ainvoke(messages, **invoke_kwargs)  # type: ignore[arg-type]
        except Exception as exc:
            record_token_error(f"llm_query failed: {type(exc).__name__}: {exc}")
            logger.warning("llm_query call failed: %s", exc)
            return {"success": False, "error": f"{type(exc).__name__}: {exc}"}

        duration_ms = (time.perf_counter() - started) * 1000
        content = str(response.content) if response.content is not None else ""
        self._record_usage(response, model_name=model_name, duration_ms=duration_ms)
        return {"success": True, "result": content, "model": model_name or ""}

    def _record_usage(
        self,
        response: object,
        *,
        model_name: str | None,
        duration_ms: float,
    ) -> None:
        """Extract token usage from the response and record it to the shared tracker."""
        usage_metadata = getattr(response, "usage_metadata", None)
        if not usage_metadata or not isinstance(usage_metadata, dict):
            return

        prompt_tokens = int(usage_metadata.get("input_tokens") or 0)
        completion_tokens = int(usage_metadata.get("output_tokens") or 0)
        total_tokens = int(usage_metadata.get("total_tokens") or 0)
        if total_tokens <= 0:
            total_tokens = prompt_tokens + completion_tokens
        if total_tokens <= 0:
            return

        usage: dict[str, object] = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
        }
        cost = compute_cost_by_tokens(
            model=model_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
        record_token_usage(
            usage,
            model_name=model_name,
            duration_ms=duration_ms,
            cost_usd=float(cost.usd),
            cost_status=cost.status.value if hasattr(cost, "status") else "estimated",
            cache_savings_usd=0.0,
        )


class LlmQueryBatchedTool(LlmQueryTool):
    """PTC tool that runs multiple lightweight LLM sub-calls concurrently.

    Results preserve the order of the input prompts. Per-prompt failures are
    isolated (returned as an error entry) and never abort the remaining calls.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str = "llm_query_batched"
    description: str = (
        "Call the LLM directly with multiple prompts in parallel. Returns a list of "
        "per-prompt results in the same order as the input. Far more efficient than a "
        "loop of llm_query for many independent prompts. Each prompt should be "
        "self-contained; do not expect cross-prompt context."
    )
    args_schema: type[BaseModel] = LlmQueryBatchedInput

    def _run(
        self,
        prompts: list[str],
        system: str | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        max_concurrent: int = 5,
    ) -> object:
        raise NotImplementedError("LlmQueryBatchedTool only supports async execution.")

    async def _arun(
        self,
        prompts: list[str],
        system: str | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        max_concurrent: int = 5,
    ) -> object:
        if not prompts:
            return {"success": True, "results": [], "model": "", "failed": 0}
        if len(prompts) > _MAX_BATCH_QUERIES:
            return {
                "success": False,
                "error": f"Too many prompts: {len(prompts)} (max {_MAX_BATCH_QUERIES}). "
                "Batch in smaller groups.",
            }

        semaphore = asyncio.Semaphore(max_concurrent)
        started = time.perf_counter()

        async def _run_one(prompt: str) -> dict[str, object]:
            async with semaphore:
                return await self._query_one(
                    prompt=prompt,
                    system=system,
                    model=model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )

        results = await asyncio.gather(*(_run_one(p) for p in prompts))
        duration_ms = (time.perf_counter() - started) * 1000
        failed = sum(1 for r in results if not r.get("success"))

        model_name: str | None = None
        for r in results:
            candidate = r.get("model")
            if isinstance(candidate, str) and candidate:
                model_name = candidate
                break
        if model_name is None:
            llm = await self._resolve_llm(model)
            model_name = _extract_model_name(llm)

        return {
            "success": True,
            "results": results,
            "model": model_name or "",
            "failed": failed,
            "duration_ms": round(duration_ms, 1),
        }
