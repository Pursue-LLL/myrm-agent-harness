"""Security boundary middleware.

Adds the global SECURITY_BOUNDARY_SYSTEM_RULES as an independent SystemMessage so the
model knows the boundary tags (<<<UNTRUSTED_DATA>>>, <<<TOOL_OUTPUT>>>, <skills_sop>)
that mark content it must not treat as instructions. The main System Prompt stays
untouched, so its cross-user Prompt Cache is not affected.

Placement:
    State merges a returned message by appending it, so the rules land after the
    messages already in state: behind the latest user message on the first model call
    of a run. They stay at that position for the rest of the run, which keeps the
    prefix stable across the model calls of one tool loop. A run that already carries
    the rules is left alone.

[INPUT]
- agent.security.detection.content_boundary::SECURITY_BOUNDARY_SYSTEM_RULES (POS: Content boundary defense core. Five-layer defense-in-depth (Unicode folding, structural framing strip, marker sanitization, random boundaries, pattern detection) for prompt injection prevention.)

[OUTPUT]
- SecurityBoundaryMiddleware: Middleware to add the security boundary rules as a SystemMessage.

[POS]
Security boundary middleware.
"""

from __future__ import annotations

from collections.abc import Sequence

from langchain.agents.middleware import AgentMiddleware, AgentState
from langchain_core.messages import AnyMessage, BaseMessage, SystemMessage
from langgraph.runtime import Runtime

from myrm_agent_harness.agent.security.detection.content_boundary import SECURITY_BOUNDARY_SYSTEM_RULES

_RULES_MARKER = "<data_boundary_rules"


def _carries_rules(messages: Sequence[AnyMessage]) -> bool:
    return any(
        isinstance(message, SystemMessage) and isinstance(message.content, str) and _RULES_MARKER in message.content
        for message in messages
    )


class SecurityBoundaryMiddleware(AgentMiddleware):
    """Middleware to add the security boundary rules as a SystemMessage once per run."""

    def before_model(self, state: AgentState, runtime: Runtime) -> dict[str, Sequence[BaseMessage]] | None:
        messages = state.get("messages", [])
        if not messages or _carries_rules(messages):
            return None
        return {"messages": [SystemMessage(content=SECURITY_BOUNDARY_SYSTEM_RULES)]}

    def after_model(self, state: AgentState, runtime: Runtime) -> dict[str, Sequence[BaseMessage]] | None:
        return None
