"""Lightweight health check for model probing.

Provides minimal-cost health checks using 1-token requests.

[INPUT]

[OUTPUT]
- lightweight_health_check: Lightweight health check function

[POS]
Lightweight health check. Uses 1-token test to minimize probing cost.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def lightweight_health_check(
    llm: Any,
    timeout_s: float = 5.0,
) -> bool:
    """Perform lightweight health check on LLM.

    Uses minimal prompt (1-2 tokens) and max_tokens=1 to minimize cost.

    Args:
        llm: LLM instance to check
        timeout_s: Timeout in seconds (default: 5s)

    Returns:
        True if model is healthy, False otherwise
    """
    try:
        # Import here to avoid circular dependency
        from langchain_core.messages import HumanMessage

        # Use minimal prompt (1-2 tokens)
        messages = [HumanMessage(content="Hi")]

        # Call with minimal token limit
        response = await llm.ainvoke(
            messages,
            config={"max_tokens": 1, "timeout": timeout_s},
        )

        # Any response means model is healthy
        return bool(response)

    except TimeoutError:
        logger.debug("Health check timed out")
        return False
    except Exception as e:
        logger.debug(f"Health check failed: {type(e).__name__}: {e}")
        return False


async def lightweight_health_check_with_retry(
    llm: Any,
    max_attempts: int = 2,
    timeout_s: float = 5.0,
) -> bool:
    """Perform lightweight health check with retry.

    Args:
        llm: LLM instance to check
        max_attempts: Maximum number of attempts (default: 2)
        timeout_s: Timeout per attempt in seconds (default: 5s)

    Returns:
        True if model is healthy, False otherwise
    """
    for attempt in range(max_attempts):
        if await lightweight_health_check(llm, timeout_s):
            return True

        if attempt < max_attempts - 1:
            logger.debug(f"Health check attempt {attempt + 1} failed, retrying...")

    return False
