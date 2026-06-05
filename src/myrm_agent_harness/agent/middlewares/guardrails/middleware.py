"""Guardrail Middleware for evaluating tool calls against policies."""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from myrm_agent_harness.agent.middlewares.guardrails.core import (
    GuardrailDecision,
    GuardrailProvider,
    GuardrailReason,
    GuardrailRequest,
)
from myrm_agent_harness.utils.logger_utils import get_agent_logger

logger = get_agent_logger(__name__)


class GuardrailMiddleware(AgentMiddleware[object, object]):
    """Evaluate tool calls against a GuardrailProvider chain before execution.

    Enables fine-grained, parameter-aware authorization policies.
    """

    def __init__(
        self,
        providers: list[GuardrailProvider],
        *,
        fail_closed: bool = True,
        agent_id: str | None = None,
        session_id: str | None = None,
    ):
        self.providers = providers
        self.fail_closed = fail_closed
        self.agent_id = agent_id
        self.session_id = session_id

    def _build_request(self, request: ToolCallRequest) -> GuardrailRequest:
        tool_name = str(request.tool_call.get("name", ""))
        tool_input = request.tool_call.get("args")
        if not isinstance(tool_input, dict):
            tool_input = {}

        return GuardrailRequest(
            tool_name=tool_name,
            tool_input=tool_input,
            agent_id=self.agent_id,
            session_id=self.session_id,
            timestamp=datetime.now(UTC).isoformat(),
        )

    def _build_denied_message(self, request: ToolCallRequest, decision: GuardrailDecision) -> ToolMessage:
        tool_name = str(request.tool_call.get("name", "unknown_tool"))
        tool_call_id = str(request.tool_call.get("id", "missing_id"))
        reason_text = decision.reasons[0].message if decision.reasons else "blocked by guardrail policy"
        reason_code = decision.reasons[0].code if decision.reasons else "oap.denied"

        return ToolMessage(
            content=(
                f"Error: [SECURITY_GUARDRAIL] Execution of '{tool_name}' was BLOCKED.\n"
                f"Reason: {reason_text} (Code: {reason_code}).\n"
                f"Hint: This is a strict policy enforcement. Do not retry with the same arguments. Choose an alternative approach or inform the user."
            ),
            tool_call_id=tool_call_id,
            name=tool_name,
            status="error",
            additional_kwargs={"error_category": "guardrail_blocked", "guardrail_code": reason_code},
        )

    async def on_tool_start(self, tool: str, input_str: str, **kwargs: object) -> str | None:
        """Legacy compatibility for string-based check if needed.

        We implement the actual interception in wrap_tool_call/awrap_tool_call instead.
        """
        return None

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:

        if not self.providers:
            return await handler(request)

        gr = self._build_request(request)

        for provider in self.providers:
            try:
                decision = await provider.aevaluate(gr)
            except Exception as e:
                logger.exception(f"Guardrail provider '{provider.name}' error: {e}")
                if self.fail_closed:
                    decision = GuardrailDecision(
                        allow=False,
                        reasons=[
                            GuardrailReason(
                                code="oap.evaluator_error", message=f"guardrail error in {provider.name} (fail-closed)"
                            )
                        ],
                    )
                else:
                    continue

            if not decision.allow:
                code = decision.reasons[0].code if decision.reasons else "unknown"
                logger.warning(f"Guardrail denied: tool={gr.tool_name} provider={provider.name} code={code}")

                # Report to audit
                from myrm_agent_harness.agent.security.audit import record_decision

                record_decision(
                    gr.tool_name,
                    "GUARDRAIL_BLOCKED",
                    f"provider={provider.name} code={code} reason={decision.reasons[0].message if decision.reasons else ''}",
                )

                return self._build_denied_message(request, decision)

        return await handler(request)
