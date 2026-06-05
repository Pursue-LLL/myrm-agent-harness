"""Rate Limit Middleware.

[INPUT]
- agent.middlewares.base::AgentMiddleware (POS: Middleware base class)
- toolkits.llms.rate_limit::RateLimitTracker, parse_rate_limit_headers (POS: Rate limit tracking)
- toolkits.llms.rate_limit.types::RateLimitState (POS: Rate limit data structures)
- utils.runtime.progress_sink::get_tool_progress_sink (POS: SSE event emission)

[OUTPUT]
- RateLimitMiddleware: Proactive rate-limit throttling middleware. Detects provider from HTTP header
  signatures, sleeps only when all tracked providers are exhausted (shortest recovery, capped at
  MAX_PROACTIVE_WAIT), and emits SSE events for frontend awareness.
- _detect_provider_from_headers: Infer LLM provider from HTTP response headers.
- _compute_min_recovery_seconds: Smallest positive recovery time across exhausted buckets.
- MAX_PROACTIVE_WAIT: Upper bound (120s) for proactive sleep duration.

[POS]
Middleware for proactive rate limit tracking, warning emission, and proactive throttling.
"""

import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage

from myrm_agent_harness.toolkits.llms.rate_limit import (
    RateLimitTracker,
    parse_rate_limit_headers,
)
from myrm_agent_harness.toolkits.llms.rate_limit.types import RateLimitState
from myrm_agent_harness.utils.logger_utils import get_agent_logger
from myrm_agent_harness.utils.runtime.progress_sink import get_tool_progress_sink

logger = get_agent_logger(__name__)

_ANTHROPIC_HEADER_PREFIX = "anthropic-ratelimit-"
MAX_PROACTIVE_WAIT = 120.0


def _detect_provider_from_headers(headers: Mapping[str, str]) -> str:
    """Detect LLM provider from HTTP response header signatures.

    Anthropic uses ``anthropic-ratelimit-*`` headers; all other providers
    (OpenAI, DeepSeek, Kimi, MiMo, Qwen, GLM, OpenRouter, …) use the
    standard ``x-ratelimit-*`` format.
    """
    for key in headers:
        if key.lower().startswith(_ANTHROPIC_HEADER_PREFIX):
            return "anthropic"
    return "openai"


def _compute_min_recovery_seconds(state: RateLimitState) -> float:
    """Return the smallest positive remaining-seconds across all exhausted buckets."""
    candidates: list[float] = []
    if state.rpm and state.rpm.remaining < 1:
        candidates.append(state.rpm.remaining_seconds_now)
    if state.rph and state.rph.remaining < 1:
        candidates.append(state.rph.remaining_seconds_now)
    if state.tpm and state.tpm.remaining < 1000:
        candidates.append(state.tpm.remaining_seconds_now)
    if state.tph and state.tph.remaining < 1000:
        candidates.append(state.tph.remaining_seconds_now)
    positive = [t for t in candidates if t > 0]
    return min(positive) if positive else 0.0


class RateLimitMiddleware(AgentMiddleware[Any, Any]):
    """Middleware for tracking LLM rate limits and proactive throttling.

    Parses rate limit headers from LLM responses, updates the global tracker,
    emits warnings if usage exceeds the threshold, and proactively sleeps
    if the rate limit is exhausted before the next call.
    """

    warning_threshold_pct: float = 0.8
    debounce_seconds: float = 300.0
    _last_warning_times: dict[tuple[str, str], float]

    def __init__(
        self,
        warning_threshold_pct: float = 0.8,
        debounce_seconds: float = 300.0,
        **kwargs: Any,
    ) -> None:
        """Initialize the middleware."""
        super().__init__(**kwargs)
        self.warning_threshold_pct = warning_threshold_pct
        self.debounce_seconds = debounce_seconds
        self._last_warning_times = {}

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse | Any:
        raise NotImplementedError("RateLimitMiddleware does not support synchronous wrap_model_call")

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        """Intercept the model request to proactively throttle and parse headers."""

        # --- Proactive Throttling ---
        # Only sleep when *all* tracked providers are exhausted (if any single
        # provider can still serve requests, the failover engine will use it).
        # When sleeping, use the *shortest* recovery time (the first provider
        # to recover unblocks the call), capped at MAX_PROACTIVE_WAIT.
        tracker = RateLimitTracker.get()
        all_states = tracker.get_all_states()

        if all_states:
            exhausted_waits: list[float] = []
            for state in all_states:
                if not state.can_consume(tokens=1000, requests=1):
                    recovery = _compute_min_recovery_seconds(state)
                    if recovery > 0:
                        exhausted_waits.append(recovery)

            if len(exhausted_waits) == len(all_states):
                wait_seconds = min(min(exhausted_waits), MAX_PROACTIVE_WAIT)

                logger.warning(
                    "Proactive Throttling: all tracked providers exhausted, sleeping %.1fs (cap %ds)",
                    wait_seconds,
                    int(MAX_PROACTIVE_WAIT),
                )

                sink = get_tool_progress_sink()
                if sink:
                    with contextlib.suppress(Exception):
                        await sink.emit(
                            {
                                "type": "rate_limit_throttled",
                                "data": {"wait_seconds": round(wait_seconds, 1)},
                            }
                        )

                await asyncio.sleep(wait_seconds)

        # --- Call the model ---
        response = await handler(request)

        # --- Parse rate-limit headers from the response ---
        try:
            last_msg = response.result[-1] if response.result else None
            if isinstance(last_msg, AIMessage):
                response_metadata = last_msg.response_metadata

                if response_metadata and "headers" in response_metadata:
                    headers = response_metadata["headers"]
                    model_name = response_metadata.get("model_name", "unknown")
                    provider = _detect_provider_from_headers(headers)

                    state = parse_rate_limit_headers(headers, provider, model_name)
                    if state:
                        updated = tracker.update(state)
                        if updated:
                            sink = get_tool_progress_sink()
                            if sink:
                                await sink.emit(
                                    {
                                        "type": "rate_limit_updated",
                                        "data": {
                                            "provider": state.provider,
                                            "model": state.model,
                                        },
                                    }
                                )

                            if state.highest_usage_pct >= self.warning_threshold_pct:
                                await self._check_and_emit_warning(state, sink)
        except Exception as e:
            logger.debug("Failed to parse rate limit headers: %s", e)

        return response

    async def _check_and_emit_warning(self, state: RateLimitState, sink: Any) -> None:
        """Check debounce and emit warning if necessary."""
        now = time.time()
        key = (state.provider, state.model)
        last_warning = self._last_warning_times.get(key, 0.0)

        if now - last_warning >= self.debounce_seconds:
            self._last_warning_times[key] = now

            pct_str = f"{state.highest_usage_pct * 100:.1f}%"
            logger.warning(
                "Rate limit usage high for %s/%s: %s",
                state.provider,
                state.model,
                pct_str,
            )

            if sink:
                try:
                    await sink.emit(
                        {
                            "type": "rate_limit_warning",
                            "data": {
                                "provider": state.provider,
                                "model": state.model,
                                "usage_pct": state.highest_usage_pct,
                            },
                        }
                    )
                except Exception as e:
                    logger.debug("Failed to emit rate limit warning: %s", e)
