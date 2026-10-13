"""Cancel-aware execution boundary for the browser tools.

[INPUT]
- utils.runtime.cancellation::run_until_cancelled, OperationCancelledError (POS: request-level cancellation token; run_until_cancelled is the boundary for operations that cannot observe it)
- session::BrowserSession (POS: browser session aggregate root; recover_active_tab heals a page an aborted action left unresponsive, take_tab_reset_notice tells the model about it)

[OUTPUT]
- apply_cancel_boundary: wrap every tool's coroutine in place so a stopped run releases the browser
- CANCELLED_RESULT: the result a tool returns when the run was stopped under it

[POS]
Cancel-aware execution boundary for the browser tools. Stopping a run only flips the request's
cancellation token. A browser action blocked inside the driver (a navigation to a server that
never answers, a script loop) never looks at that flag, so the tool would hold the session until
its own timeout. This boundary races each tool call against the token, aborts the call, heals the
tab and hands the model a plain result instead of an error. A run torn down from outside the
request (executor timeout, stuck-task watchdog, shutdown) cancels the tool without the token, and
nothing may call the session again soon, so the tab is healed there too before the cancellation
continues. A healed tab is blank, so the next text result carries the session's reset notice.
Mutates the tools it receives, because `with_dynamic_hints` already produced the final copies.
"""

from __future__ import annotations

import asyncio
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
            result = await run_until_cancelled(coroutine(*args, **kwargs))
        except OperationCancelledError:
            await session.recover_active_tab()
            return CANCELLED_RESULT
        except asyncio.CancelledError:
            await session.recover_active_tab()
            raise
        return _with_tab_reset_notice(result, session)

    return run


def _with_tab_reset_notice(result: object, session: BrowserSession) -> object:
    """Prefix a text result with the pending tab-reset notice; other results leave it pending."""
    if not isinstance(result, str):
        return result
    notice = session.take_tab_reset_notice()
    return result if notice is None else f"{notice}\n\n{result}"
