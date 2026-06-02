"""Async-context-bound failover/recovery emitter for the fallback subsystem.

[INPUT]
- .events (POS: FailoverEvent / RecoveryEvent data classes)

[OUTPUT]
- FailoverEmitter: Protocol for emitters that publish failover/recovery events
- failover_emitter_ctx: ContextVar holding the active emitter for the current coroutine
- with_failover_emitter(): async context manager that scopes an emitter to a code block
- get_active_failover_emitter(): safe accessor returning None when no emitter is bound

[POS]
Framework-level decoupling layer between ``ModelFallbackManager`` and the
business surfaces that need to surface failover events (SSE, log sinks,
telemetry pipelines). The framework stays free of any transport-specific
concept — it only knows how to invoke a ``FailoverEmitter`` if one has been
bound to the current async context. This mirrors ``user_credentials_ctx`` in
``core/security/types.py`` and preserves strict harness/server boundary.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import Protocol, runtime_checkable

from .events import FailoverEvent, RecoveryEvent


@runtime_checkable
class FailoverEmitter(Protocol):
    """Sink for failover / recovery notifications.

    Implementations translate domain events into transport-specific payloads
    (SSE chunks for the streaming agent loop, structured log entries for the
    SaaS control plane, telemetry pings, etc.). All methods MUST be safe to
    invoke concurrently and MUST NOT raise — the manager guards against
    callback failures but a misbehaving emitter still pollutes logs.
    """

    async def emit_failover(self, event: FailoverEvent) -> None:
        """Notify subscribers that a fallback transition has happened."""

    async def emit_recovery(self, event: RecoveryEvent) -> None:
        """Notify subscribers that a previously-cold model recovered."""


failover_emitter_ctx: ContextVar[FailoverEmitter | None] = ContextVar(
    "failover_emitter_ctx", default=None
)


@asynccontextmanager
async def with_failover_emitter(emitter: FailoverEmitter) -> AsyncIterator[None]:
    """Bind ``emitter`` to the current async context for the duration of the block.

    The previous emitter (if any) is restored on exit even when the inner
    code raises. Nested ``with_failover_emitter`` calls stack naturally because
    ``ContextVar.set`` returns a per-call reset token.
    """
    token = failover_emitter_ctx.set(emitter)
    try:
        yield
    finally:
        failover_emitter_ctx.reset(token)


def get_active_failover_emitter() -> FailoverEmitter | None:
    """Return the emitter bound to the current context, or ``None`` if absent.

    Callers MUST treat ``None`` as a normal "no subscriber wired up" state —
    this is the default for batch jobs, unit tests, and any code path that
    runs without a streaming surface.
    """
    return failover_emitter_ctx.get()
