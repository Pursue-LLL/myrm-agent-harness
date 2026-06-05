"""Subagent limit middleware.

Truncates excess 'delegate_task' tool calls from a single model response.
Prevents LLM fan-out (e.g., the model going crazy and emitting 20 delegate_task calls at once),
which could exhaust API rate limits and system resources.

[INPUT]

[OUTPUT]
- ModelResponse.result with truncated tool_calls if limit exceeded

[POS]
Subagent limit middleware. Ensures the LLM cannot spawn more than MAX_CONCURRENT_SUBAGENTS
in a single turn.
"""

import dataclasses
import logging
from collections.abc import Awaitable, Callable

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage

logger = logging.getLogger(__name__)

MAX_CONCURRENT_SUBAGENTS = 3


def _truncate_delegate_calls(message: AIMessage, max_concurrent: int) -> AIMessage | None:
    """Truncate excess delegate_task tool calls from an AIMessage.

    Returns a new AIMessage with truncated tool_calls if exceeded, otherwise None.
    """
    if not hasattr(message, "tool_calls") or not message.tool_calls:
        return None

    delegate_calls = [tc for tc in message.tool_calls if tc["name"] == "delegate_task_tool"]
    if len(delegate_calls) <= max_concurrent:
        return None

    logger.warning("LLM emitted %d delegate_task calls. Truncating to %d.", len(delegate_calls), max_concurrent)

    allowed_delegate_ids = {tc["id"] for tc in delegate_calls[:max_concurrent]}

    new_tool_calls = [
        tc for tc in message.tool_calls if tc["name"] != "delegate_task_tool" or tc["id"] in allowed_delegate_ids
    ]

    return AIMessage(
        content=message.content,
        additional_kwargs=message.additional_kwargs,
        response_metadata=message.response_metadata,
        id=message.id,
        name=message.name,
        tool_calls=new_tool_calls,
    )


class SubagentLimitMiddleware(AgentMiddleware):  # type: ignore[type-arg]
    """Truncate excess delegate_task tool calls in the LLM response."""

    name = "subagent_limit_middleware"

    async def awrap_model_call(
        self, request: ModelRequest, handler: Callable[[ModelRequest], Awaitable[ModelResponse]]
    ) -> ModelResponse:
        response = await handler(request)

        if not response.result:
            return response

        last_msg = response.result[-1]
        if not isinstance(last_msg, AIMessage):
            return response

        truncated_msg = _truncate_delegate_calls(last_msg, MAX_CONCURRENT_SUBAGENTS)
        if truncated_msg is not None:
            new_result = [*response.result[:-1], truncated_msg]
            return dataclasses.replace(response, result=new_result)

        return response


subagent_limit_middleware = SubagentLimitMiddleware()
