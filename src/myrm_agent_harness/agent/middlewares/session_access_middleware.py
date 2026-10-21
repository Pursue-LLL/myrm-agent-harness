"""Inject per-turn session directory access context for the agent.

[POS]
See module docstring.
"""

from __future__ import annotations

from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import SystemMessage

from myrm_agent_harness.agent.middlewares._session_context import (
    get_security_config,
    get_workspace_root,
)
from myrm_agent_harness.agent.security.session_access import render_session_access_context

_SESSION_ACCESS_MARKER = "<session-access>"


class SessionAccessMiddleware(AgentMiddleware):  # type: ignore[type-arg]
    """Append available directory roots before each model call."""

    def before_model(self, state: dict[str, Any], runtime: Any) -> dict[str, Any] | None:
        config = get_security_config()
        if config is None:
            return None

        workspace_root = get_workspace_root() or None
        block = render_session_access_context(config.path_policy, workspace_root)
        if not block:
            return None

        messages = state.get("messages", [])
        if not isinstance(messages, list):
            return None

        for msg in messages:
            if (
                isinstance(msg, SystemMessage)
                and isinstance(msg.content, str)
                and _SESSION_ACCESS_MARKER in msg.content
            ):
                return None

        content = f"{_SESSION_ACCESS_MARKER}\n{block}\n</session-access>"
        new_messages = [*messages, SystemMessage(content=content)]
        return {"messages": new_messages}

    def after_model(self, state: dict[str, Any], runtime: Any) -> dict[str, Any] | None:
        return None
