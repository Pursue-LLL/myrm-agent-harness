"""Request-scoped escalation bindings (server sets per agent run; harness reads)."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.browser.pool.config import LaunchMode
    from myrm_agent_harness.toolkits.web_fetch.escalation.protocols import FetchEscalationProvider

_providers_ctx: ContextVar[list[FetchEscalationProvider] | None] = ContextVar(
    "web_fetch_escalation_providers",
    default=None,
)
_launch_mode_ctx: ContextVar[LaunchMode | None] = ContextVar(
    "web_fetch_browser_launch_mode",
    default=None,
)


def get_bound_escalation_providers() -> list[FetchEscalationProvider] | None:
    return _providers_ctx.get()


def get_bound_browser_launch_mode() -> LaunchMode | None:
    return _launch_mode_ctx.get()


@contextmanager
def bind_web_fetch_escalation_context(
    *,
    providers: list[FetchEscalationProvider] | None,
    launch_mode: LaunchMode | None,
):
    """Bind escalation providers and browser launch mode for the current async task."""
    provider_token: Token[list[FetchEscalationProvider] | None] = _providers_ctx.set(providers)
    launch_token: Token[LaunchMode | None] = _launch_mode_ctx.set(launch_mode)
    try:
        yield
    finally:
        _providers_ctx.reset(provider_token)
        _launch_mode_ctx.reset(launch_token)
