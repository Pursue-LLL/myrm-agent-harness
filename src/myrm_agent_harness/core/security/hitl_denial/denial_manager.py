"""HITL Denial Event Manager and Synthetic ToolResult Producer.

[INPUT]
- List of denied tool calls, total tool calls requested, policy configuration.

[OUTPUT]
- ProcessDenialsResult with synthetic ToolResult blocks and stop/continue resolution.

[POS]
- Harness core security engine for AgentScope-Java #2546 HITL denial tool results and all-denied handling.
"""

from __future__ import annotations

from collections.abc import Sequence

from .types import (
    DenialResolutionPolicy,
    ProcessDenialsResult,
    SyntheticToolResultBlock,
    ToolDenialItem,
)


class HitlDenialManager:
    """Manages manual HITL denials, ensuring LLM context integrity with explicit denial results."""

    def __init__(
        self,
        default_all_denied_policy: DenialResolutionPolicy = DenialResolutionPolicy.CONTINUE,
    ) -> None:
        self._default_policy = default_all_denied_policy

    @staticmethod
    def format_denial_message(item: ToolDenialItem) -> str:
        """Format an informative synthetic tool output indicating user denial."""
        msg = (
            f"[Action Denied by User]: Tool '{item.tool_name}' execution was rejected."
        )
        if item.reason:
            msg += f" Reason: {item.reason}."
        if item.custom_feedback:
            msg += f" User Guidance: {item.custom_feedback}."
        msg += (
            " Please reconsider your strategy or propose an alternative safe approach."
        )
        return msg

    def process_denials(
        self,
        denied_items: Sequence[ToolDenialItem],
        total_tool_calls_in_step: int,
        override_policy: DenialResolutionPolicy | None = None,
    ) -> ProcessDenialsResult:
        """Process denied tool calls, creating synthetic tool result blocks and evaluating all-denied actions."""
        synthetic_results: list[SyntheticToolResultBlock] = []

        for item in denied_items:
            output = self.format_denial_message(item)
            synthetic_results.append(
                SyntheticToolResultBlock(
                    tool_call_id=item.tool_call_id,
                    tool_name=item.tool_name,
                    output=output,
                    is_error=True,
                    metadata={
                        "denied_by": "human_in_the_loop",
                        "reason": item.reason,
                        "has_custom_feedback": str(bool(item.custom_feedback)),
                    },
                )
            )

        total_denied = len(denied_items)
        all_tools_denied = (
            total_tool_calls_in_step > 0 and total_denied >= total_tool_calls_in_step
        )
        policy = override_policy or self._default_policy
        stop_requested = all_tools_denied and policy == DenialResolutionPolicy.STOP

        return ProcessDenialsResult(
            all_tools_denied=all_tools_denied,
            total_requested=total_tool_calls_in_step,
            total_denied=total_denied,
            resolution_action=policy,
            synthetic_results=synthetic_results,
            stop_requested=stop_requested,
        )
