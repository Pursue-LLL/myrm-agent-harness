"""Liveness probe for failover candidates and reachability checks.

[INPUT]
- langchain_core.messages::HumanMessage (POS: the trivial probe prompt)

[OUTPUT]
- ProbeTarget: the slice of a chat model the probe relies on (``ainvoke`` with one message list)
- HealthProbeResult: structured probe outcome (ok / error_kind / error / latency_ms)
- probe_llm_health: probe a chat model and report the outcome together with its failure reason
- lightweight_health_check: send one trivial request and report whether the model answered within a hard deadline

[POS]
Cheap liveness probe. The deadline is enforced here with ``asyncio.wait_for`` because a model instance's own
request timeout is minutes long and would otherwise hold the caller on a hung endpoint. The request itself is
the model's normal one: capping its output tokens is not safe (reasoning models reject a budget below their
thinking allowance), so the deadline is what bounds the probe's cost.

Failures are classified instead of flattened: callers that only need a boolean keep using
``lightweight_health_check``, while callers that must explain the failure to a human (the server's provider
connection test) read ``HealthProbeResult.error_kind`` / ``error`` to tell "the endpoint did not answer in
time" apart from "the provider rejected the request".
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Literal, Protocol

from langchain_core.messages import HumanMessage

logger = logging.getLogger(__name__)

DEFAULT_HEALTH_PROBE_TIMEOUT_S = 5.0
_MAX_PROBE_ERROR_CHARS = 500

HealthProbeErrorKind = Literal["none", "timeout", "provider_error"]


@dataclass(frozen=True, slots=True)
class HealthProbeResult:
    """Outcome of a single liveness probe.

    Attributes:
        ok: True when the model answered inside the deadline.
        error_kind: ``none`` on success, ``timeout`` when the deadline elapsed,
            ``provider_error`` when the provider answered with an error or an empty body.
        error: Human-readable failure reason (None on success).
        latency_ms: Wall-clock duration of the probe in milliseconds.
    """

    ok: bool
    error_kind: HealthProbeErrorKind
    error: str | None = None
    latency_ms: int | None = None


class ProbeTarget(Protocol):
    """The part of a chat model the probe calls; any LangChain chat model satisfies it."""

    async def ainvoke(self, messages: list[HumanMessage], /) -> object: ...


class _ProviderTimeoutError(Exception):
    """The provider itself reported a timeout before the probe deadline elapsed."""


def _truncate(text: str) -> str:
    """Clamp provider error text so a verbose upstream payload cannot flood the UI."""
    collapsed = " ".join(text.split())
    if len(collapsed) <= _MAX_PROBE_ERROR_CHARS:
        return collapsed
    return collapsed[:_MAX_PROBE_ERROR_CHARS] + "…"


async def probe_llm_health(
    llm: ProbeTarget,
    timeout_s: float = DEFAULT_HEALTH_PROBE_TIMEOUT_S,
) -> HealthProbeResult:
    """Probe ``llm`` with a trivial prompt and classify the outcome.

    A call still pending at the deadline is cancelled, so a hung endpoint costs the caller at most
    ``timeout_s`` instead of the model's own request timeout.

    Args:
        llm: Chat model to probe
        timeout_s: Hard deadline in seconds (default: 5s)

    Returns:
        HealthProbeResult carrying the outcome, the failure classification and the elapsed time
    """
    started = time.monotonic()

    def _elapsed_ms() -> int:
        return int((time.monotonic() - started) * 1000)

    async def _invoke() -> object:
        try:
            return await llm.ainvoke([HumanMessage(content="Hi")])
        except TimeoutError as e:
            # A provider-side timeout must not be confused with our own deadline elapsing.
            raise _ProviderTimeoutError(str(e)) from e

    try:
        response = await asyncio.wait_for(_invoke(), timeout=timeout_s)
    except TimeoutError:
        logger.debug("Health check timed out (deadline %.1fs)", timeout_s)
        return HealthProbeResult(
            ok=False,
            error_kind="timeout",
            error=f"No response within {timeout_s:g}s",
            latency_ms=_elapsed_ms(),
        )
    except _ProviderTimeoutError as e:
        logger.debug("Health check provider timeout: %s", e)
        return HealthProbeResult(
            ok=False,
            error_kind="provider_error",
            error=_truncate(f"TimeoutError: {e}"),
            latency_ms=_elapsed_ms(),
        )
    except Exception as e:
        logger.debug("Health check failed: %s: %s", type(e).__name__, e)
        return HealthProbeResult(
            ok=False,
            error_kind="provider_error",
            error=_truncate(f"{type(e).__name__}: {e}"),
            latency_ms=_elapsed_ms(),
        )

    if not response:
        return HealthProbeResult(
            ok=False,
            error_kind="provider_error",
            error="Provider returned an empty response",
            latency_ms=_elapsed_ms(),
        )

    return HealthProbeResult(ok=True, error_kind="none", error=None, latency_ms=_elapsed_ms())


async def lightweight_health_check(
    llm: ProbeTarget,
    timeout_s: float = DEFAULT_HEALTH_PROBE_TIMEOUT_S,
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
    return (await probe_llm_health(llm, timeout_s=timeout_s)).ok
