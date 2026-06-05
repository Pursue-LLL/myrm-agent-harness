"""Security boundary middleware.

Injects the global SECURITY_BOUNDARY_SYSTEM_RULES as an independent SystemMessage
immediately after the main System Prompt (at index 1). This ensures the LLM is
aware of boundary tags (<<<UNTRUSTED_DATA>>>, <<<TOOL_OUTPUT>>>, <skills_sop>)
while perfectly preserving cross-user Prompt Caching for the main System Prompt.

Design:
    [0] System Prompt (fixed, cross-user cache)           ← cached
    [1] Security Boundary Rules (fixed, cross-user cache) ← cached  (THIS MIDDLEWARE)
    [2] user_instructions (per-user, stable)              ← cached
    [3] <user_memory_context> Stable (per-user)          ← cached
    [4] Human: <<<UNTRUSTED_DATA>>> learned (optional)    ← advisory envelope
    [5] Human: user turns...                              ← varies per turn

[INPUT]
- agent.security.detection.content_boundary::SECURITY_BOUNDARY_SYSTEM_RULES (POS: Unicode  ID)

[OUTPUT]
- SecurityBoundaryMiddleware: Middleware to inject security boundary rules as a SystemM...

[POS]
Security boundary middleware.
"""

from __future__ import annotations

from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import SystemMessage

from myrm_agent_harness.agent.security.detection.content_boundary import SECURITY_BOUNDARY_SYSTEM_RULES


class SecurityBoundaryMiddleware(AgentMiddleware):  # type: ignore[type-arg]
    """Middleware to inject security boundary rules as a SystemMessage."""

    def before_model(self, state: dict[str, Any], runtime: Any) -> dict[str, Any] | None:
        messages = state.get("messages", [])
        if not messages:
            return None

        # Find the first SystemMessage (the main system prompt)
        first_system_idx = -1
        for i, msg in enumerate(messages):
            if isinstance(msg, SystemMessage):
                first_system_idx = i
                break

        if first_system_idx == -1:
            # If no SystemMessage exists, just prepend it
            insert_idx = 0
        else:
            # Insert immediately after the first SystemMessage
            insert_idx = first_system_idx + 1

        # Check if already injected (idempotency)
        if insert_idx < len(messages):
            existing_msg = messages[insert_idx]
            if (
                isinstance(existing_msg, SystemMessage)
                and isinstance(existing_msg.content, str)
                and "<data_boundary_rules" in existing_msg.content
            ):
                return None

        new_messages = list(messages)
        boundary_msg = SystemMessage(content=SECURITY_BOUNDARY_SYSTEM_RULES)
        new_messages.insert(insert_idx, boundary_msg)

        return {"messages": new_messages}

    def after_model(self, state: dict[str, Any], runtime: Any) -> dict[str, Any] | None:
        return None
