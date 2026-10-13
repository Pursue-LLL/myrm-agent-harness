"""Cancel-aware execution boundary for the browser tools.

[INPUT]
- utils.runtime.cancellation::run_until_cancelled, OperationCancelledError (POS: aborts an operation once the request token fires)
- session::BrowserSession (POS: replaces the active tab when an aborted action left its page unresponsive)

[OUTPUT]
- apply_cancel_boundary: wrap every tool's coroutine in place so a stopped run releases the browser
- CANCELLED_RESULT: the result a tool returns when the run was stopped under it

[POS]
Stopping a run only flips the request's cancellation token. A browser action blocked inside the
driver (a navigation to a server that never answers, a script loop) never looks at that flag, so
the tool would hold the session until its own timeout. This boundary races each tool call against
the token, aborts the call, heals the tab and hands the model a plain result instead of an error.
Mutates the tools it receives, because `with_dynamic_hints` already produced the final copies.
"""

from __future__ import annotations

import functools
from typing import TYPE_CHECKING

from langchain_core.tools import BaseTool, StructuredTool

from myrm_agent_harness.utils.runtime.cancellation import OperationCancelledError, run_until_cancelled

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ..session import BrowserSession

CANCELLED_RESULT = (
    "[cancelled] The run was stopped while this browser action was in progress, so it may have been "
    "only partially applied. Inspect the page before relying on its state."
)


def apply_cancel_boundary(tools: list[BaseTool], session: BrowserSession) -> list[BaseTool]:
    """Make every tool in `tools` abort promptly when the current run is stopped.

    Raises:
        TypeError: a tool has no coroutine to guard (it would silently stay uncancellable).
    """
    for tool in tools:
        if not isinstance(tool, StructuredTool) or tool.coroutine is None:
            raise TypeError(f"Cannot guard {tool.name}: it has no coroutine")
        tool.coroutine = _cancel_aware(tool.coroutine, session)
    return tools


def _cancel_aware(
    coroutine: Callable[..., Awaitable[object]], session: BrowserSession
) -> Callable[..., Awaitable[object]]:
    @functools.wraps(coroutine)
    async def run(*args: object, **kwargs: object) -> object:
        try:
            return await run_until_cancelled(coroutine(*args, **kwargs))
        except OperationCancelledError:
            await session.recover_active_tab()
            return CANCELLED_RESULT

    return run
