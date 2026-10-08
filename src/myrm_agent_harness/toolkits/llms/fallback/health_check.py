"""Liveness probe for failover candidates and reachability checks.

[INPUT]
- langchain_core.messages::HumanMessage (POS: the trivial probe prompt)

[OUTPUT]
- ProbeTarget: the slice of a chat model the probe relies on (``ainvoke`` with one message list)
- lightweight_health_check: send one trivial request and report whether the model answered within a hard deadline

[POS]
Cheap liveness probe. The deadline is enforced here with ``asyncio.wait_for`` because a model instance's own
request timeout is minutes long and would otherwise hold the caller on a hung endpoint. The request itself is
the model's normal one: capping its output tokens is not safe (reasoning models reject a budget below their
thinking allowance), so the deadline is what bounds the probe's cost.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Protocol

from langchain_core.messages import HumanMessage

logger = logging.getLogger(__name__)


class ProbeTarget(Protocol):
    """The part of a chat model the probe calls; any LangChain chat model satisfies it."""

    async def ainvoke(self, messages: list[HumanMessage], /) -> object: ...


async def lightweight_health_check(
    llm: ProbeTarget,
    timeout_s: float = 5.0,
) -> bool:
    """Return True when ``llm`` answers a trivial prompt within ``timeout_s`` seconds.

    A call still pending at the deadline is cancelled, so a hung endpoint costs the caller at most
    ``timeout_s`` instead of the model's own request timeout.

    Args:
        llm: Chat model to probe
        timeout_s: Hard deadline in seconds (default: 5s)

    Returns:
        True if the model answered in time, False on timeout or any provider error
    """
    try:
        response = await asyncio.wait_for(llm.ainvoke([HumanMessage(content="Hi")]), timeout=timeout_s)
    except TimeoutError:
        logger.debug("Health check timed out (deadline %.1fs)", timeout_s)
        return False
    except Exception as e:
        logger.debug("Health check failed: %s: %s", type(e).__name__, e)
        return False
    return bool(response)
