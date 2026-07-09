"""Request-scoped escalation bindings (server sets per agent run; harness reads).

[POS]
ContextVar bindings for optional L4 fetch escalation providers and browser launch mode.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

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
        for ctx_var, token in (
            (_providers_ctx, provider_token),
            (_launch_mode_ctx, launch_token),
        ):
            try:
                ctx_var.reset(token)
            except ValueError:
                # Token was created in a different async context (LangGraph cancel / TestClient).
                logger.warning(
                    "Context variable reset skipped: token created in different context (%s)",
                    ctx_var.name,
                )
