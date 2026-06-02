"""Context integration for browser checkpoint metadata.

Provides utilities to inject browser state into LangGraph context for automatic checkpointing.


[INPUT]
- session::BrowserSession (POS: browser session manager)
- session_vault::SessionVault (POS: AES-256-GCM encrypted session storage)
- session_state::get_browser_state (POS: extract browser state)

[OUTPUT]
- BrowserCheckpointHelper: Helper for updating browser state in Agent context
- create_browser_context_updater: Factory for context update callback

[POS]
Integration module between browser checkpoint and Agent context. Provides utility functions for automatically
updating browser state into LangGraph context during Agent runtime, enabling seamless checkpoint/resume support.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..session import BrowserSession
    from ..session_vault import SessionVault
    from .session_state import BrowserState

logger = logging.getLogger(__name__)


class BrowserCheckpointHelper:
    """Helper for managing browser state in Agent context.

    Usage in Agent:
        helper = BrowserCheckpointHelper(browser_session, session_vault)

        # Before Agent.run()
        context = helper.get_initial_context()

        # After browser operations
        await helper.update_context(agent_context)
    """

    def __init__(
        self,
        browser_session: BrowserSession,
        session_vault: SessionVault | None = None,
    ) -> None:
        """Initialize checkpoint helper.

        Args:
            browser_session: BrowserSession instance
            session_vault: Optional SessionVault
        """
        self._session = browser_session
        self._vault = session_vault
        self._counters: dict[str, int] = {
            "snapshots": 0,
            "interactions": 0,
            "navigations": 0,
        }

    def increment_counter(self, counter_name: str) -> None:
        """Increment a task counter.

        Args:
            counter_name: Counter name (snapshots, interactions, navigations)
        """
        if counter_name in self._counters:
            self._counters[counter_name] += 1

    async def get_browser_metadata(self) -> BrowserState:
        """Get current browser state for checkpoint metadata.

        Returns:
            Dictionary with browser state
        """
        from .session_state import get_browser_state

        state = await get_browser_state(self._session, self._vault)
        state["task_counters"] = dict(self._counters)

        return state

    def get_initial_context(self) -> dict[str, dict[str, object]]:
        """Get initial context for Agent.run().

        Returns:
            Initial context dictionary
        """
        return {
            "browser_checkpoint": {
                "enabled": True,
                "counters": dict(self._counters),
            }
        }

    async def update_context(self, context: dict[str, object]) -> None:
        """Update Agent context with current browser state.

        Args:
            context: Agent context dictionary (mutable)
        """
        if "browser_checkpoint" not in context:
            context["browser_checkpoint"] = {}

        browser_meta = await self.get_browser_metadata()
        checkpoint_data = context["browser_checkpoint"]
        if isinstance(checkpoint_data, dict):
            checkpoint_data.update(browser_meta)


def create_browser_context_updater(
    browser_session: BrowserSession,
    session_vault: SessionVault | None = None,
) -> Callable[[dict[str, object]], Coroutine[object, object, None]]:
    """Factory for creating browser context update callback.

    Returns a callback that can be used to update browser state in Agent context.

    Args:
        browser_session: BrowserSession instance
        session_vault: Optional SessionVault

    Returns:
        Async callback function

    Usage:
        updater = create_browser_context_updater(session, vault)
        await updater(agent_context)
    """
    helper = BrowserCheckpointHelper(browser_session, session_vault)
    return helper.update_context
