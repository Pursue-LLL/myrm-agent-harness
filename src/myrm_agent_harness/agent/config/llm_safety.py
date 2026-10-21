"""Provider Safety — tool-history pairing gate for LLM calls made outside the middleware chain.

Direct LLM paths (summary prefix, grace call) bypass the agent middleware chain, so they call
``normalize_messages`` to pass the same gate as the main call: id hygiene, then dangling repair.

[INPUT]
- langchain_core.messages::BaseMessage (POS: Core message type definitions. All cross-channel communication data structures are defined here; zero I/O, pure data.)
- agent.middlewares.tooling.tool_history_hygiene::sanitize_tool_history (POS: Tool history hygiene middleware. Runs BEFORE dangling_tool_call_middleware.)
- agent.middlewares.tooling.dangling_tool_call_middleware::repair_dangling_tool_calls (POS: Dangling tool call repair middleware.)

[OUTPUT]
- normalize_messages(): The production sanitize → repair pair; a well-formed history is returned unchanged

[POS]
Provider safety normalization. Pure function for direct LLM paths; agent middleware covers the primary runtime.
"""

from collections.abc import Sequence

from langchain_core.messages import BaseMessage


def normalize_messages(messages: Sequence[BaseMessage]) -> list[BaseMessage]:
    """Pair tool requests and results the way the agent middleware chain does before a model call.

    Runs ``sanitize_tool_history`` (unique tool_call_ids), then ``repair_dangling_tool_calls``
    (drops orphan results, answers unanswered requests with a synthetic result). A well-formed
    history is returned as-is (same message objects, same order), so a cached prompt prefix stays
    byte-identical.

    Args:
        messages: Message sequence about to be sent to the provider.

    Returns:
        Messages safe to send to a strict provider; the input messages are never mutated.
    """
    # Imported lazily: the middleware package loads thousands of modules and pulls in
    # context_management, whose summarizer calls this function (a top-level import would be circular).
    from myrm_agent_harness.agent.middlewares.tooling.dangling_tool_call_middleware import (
        repair_dangling_tool_calls,
    )
    from myrm_agent_harness.agent.middlewares.tooling.tool_history_hygiene import sanitize_tool_history

    return repair_dangling_tool_calls(sanitize_tool_history(list(messages)))


__all__ = [
    "normalize_messages",
]
