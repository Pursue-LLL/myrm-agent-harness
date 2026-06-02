"""Resilient LLM call with automatic failover.

Provides a generic higher-order function that wraps any async LLM call
with failover logic.  Uses ``errors.classifier`` to decide whether the
error is recoverable by switching to a fallback model.

Usage::

    from myrm_agent_harness.toolkits.llms.resilient import resilient_llm_call

    title = await resilient_llm_call(
        primary_fn=lambda: llm.ainvoke(messages),
        fallback_fn=lambda: fallback_llm.ainvoke(messages),
    )

[INPUT]
- (none)

[OUTPUT]
- resilient_llm_call: Execute an async LLM call with automatic failover.

[POS]
Resilient LLM call with automatic failover.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

from myrm_agent_harness.toolkits.llms.errors.classifier import classify_error

logger = logging.getLogger(__name__)

T = TypeVar("T")


async def resilient_llm_call[T](
    primary_fn: Callable[[], Awaitable[T]],
    fallback_fn: Callable[[], Awaitable[T]] | None = None,
) -> T:
    """Execute an async LLM call with automatic failover.

    Calls *primary_fn*.  If it raises a **failoverable** error (as
    classified by ``errors.classifier.classify_error``) and *fallback_fn*
    is provided, the fallback is attempted once.

    This is the **Service-layer** failover primitive.  For Agent-layer
    failover (which requires rebuilding the LangGraph execution graph),
    see ``BaseAgent._run_astream()``.
    """
    try:
        return await primary_fn()
    except Exception as primary_exc:
        if fallback_fn is None:
            raise

        error_kind = classify_error(primary_exc)
        if not error_kind.is_failoverable:
            raise

        logger.warning(f" Service failover: {error_kind.value} → switching to fallback")
        return await fallback_fn()
