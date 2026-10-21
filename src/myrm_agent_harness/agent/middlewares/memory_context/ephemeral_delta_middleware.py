"""Inject ephemeral session deltas at the tail of the current HumanMessage (prefix cache safe).

[INPUT]
- toolkits.memory.ephemeral_delta (shared store + tail injector)
- core.context_vars::chat_id_var

[OUTPUT]
- ephemeral_delta_middleware: AgentMiddleware applying human-tail delta tags before each model call.

[POS]
Runs after memory_context_middleware; mutates only the last HumanMessage tail, never the frozen system prefix.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse

from myrm_agent_harness.core.context_vars import chat_id_var
from myrm_agent_harness.toolkits.memory.ephemeral_delta import (
    HumanTailDeltaInjector,
    get_shared_ephemeral_delta_store,
)

_injector = HumanTailDeltaInjector()


class EphemeralDeltaMiddleware(AgentMiddleware):
    name = "ephemeral_delta_middleware"

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        session_id = (chat_id_var.get() or "").strip()
        if not session_id or session_id == "default":
            return await handler(request)

        deltas = get_shared_ephemeral_delta_store().get_active_deltas(session_id)
        processed_messages = _injector.inject_deltas(list(request.messages), deltas)
        if processed_messages is not request.messages:
            request = request.override(messages=processed_messages)
        return await handler(request)


ephemeral_delta_middleware = EphemeralDeltaMiddleware()
