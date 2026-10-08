"""Event dispatcher for human-in-the-loop denial and confirmation lifecycles.

[INPUT]
- Pending tool calls and user confirmation decisions.

[OUTPUT]
- Structured HitlProcessOutcome containing tool result events and potential
  all-tools-denied aggregate events.

[POS]
- Core dispatcher emitting explicit tool_result events on manual denials
  and coordinating the halt vs resume workflow.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from myrm_agent_harness.core.security.hitl_denial_events.policy_evaluator import (
    AllToolsDeniedPolicyEvaluator,
)
from myrm_agent_harness.core.security.hitl_denial_events.types import (
    AllToolsDeniedEvent,
    AllToolsDeniedPolicy,
    ConfirmResult,
    HitlProcessOutcome,
    ToolResultEvent,
    ToolResultState,
    ToolUseBlock,
)

DEFAULT_DENIAL_REASON: str = "Permission denied by user"
DEFAULT_APPROVAL_MESSAGE: str = "Permission granted by user"


class HitlDenialEventDispatcher:
    """Dispatches tool result events on HITL confirmations and denials."""

    def __init__(
        self,
        policy_evaluator: AllToolsDeniedPolicyEvaluator | None = None,
    ) -> None:
        """Initialize dispatcher.

        Args:
            policy_evaluator: Evaluator for all-tools-denied policies.
        """
        self._policy_evaluator = (
            policy_evaluator or AllToolsDeniedPolicyEvaluator()
        )

    def process_decisions(
        self,
        session_id: str,
        step_id: str,
        tool_calls: Sequence[ToolUseBlock],
        decisions: Sequence[ConfirmResult],
        explicit_policy: AllToolsDeniedPolicy | None = None,
    ) -> HitlProcessOutcome:
        """Process batch of confirmation decisions into explicit events.

        Args:
            session_id: Active session identifier.
            step_id: Current reasoning step identifier.
            tool_calls: All tool calls proposed during this step.
            decisions: User confirmation decisions for proposed tool calls.
            explicit_policy: Optional override policy for all-denied handling.

        Returns:
            HitlProcessOutcome with generated events and loop control flags.
        """
        decision_map = {d.tool_call_id: d for d in decisions}
        now_iso = datetime.now(UTC).isoformat()

        tool_result_events: list[ToolResultEvent] = []
        denied_tools: list[ToolUseBlock] = []
        denied_reasons: dict[str, str] = {}
        confirmed_count = 0
        denied_count = 0

        for tool_call in tool_calls:
            event_id = f"evt_{uuid.uuid4().hex[:12]}"
            decision = decision_map.get(tool_call.id)

            if decision is None or not decision.confirmed:
                denied_count += 1
                denied_tools.append(tool_call)
                raw_reason = decision.reason if decision is not None else None
                reason_text = (
                    raw_reason.strip()
                    if raw_reason and raw_reason.strip()
                    else DEFAULT_DENIAL_REASON
                )
                denied_reasons[tool_call.id] = reason_text

                tool_result_events.append(
                    ToolResultEvent(
                        event_id=event_id,
                        tool_call_id=tool_call.id,
                        tool_name=tool_call.name,
                        state=ToolResultState.DENIED,
                        output_text=reason_text,
                        created_at=now_iso,
                    )
                )
            else:
                confirmed_count += 1
                tool_result_events.append(
                    ToolResultEvent(
                        event_id=event_id,
                        tool_call_id=tool_call.id,
                        tool_name=tool_call.name,
                        state=ToolResultState.ALLOWED,
                        output_text=DEFAULT_APPROVAL_MESSAGE,
                        created_at=now_iso,
                    )
                )

        total_calls = len(tool_calls)
        all_denied = total_calls > 0 and denied_count == total_calls

        all_tools_denied_event: AllToolsDeniedEvent | None = None
        can_resume = True
        terminal_reason: str | None = None

        if all_denied:
            effective_policy, should_stop, stop_reason = (
                self._policy_evaluator.evaluate(
                    denied_tools=denied_tools,
                    explicit_policy=explicit_policy,
                )
            )
            all_tools_denied_event = AllToolsDeniedEvent(
                event_id=f"all_denied_{uuid.uuid4().hex[:12]}",
                session_id=session_id,
                step_id=step_id,
                denied_tool_calls=denied_tools,
                denied_reasons=denied_reasons,
                policy_applied=effective_policy,
                should_stop=should_stop,
                stop_reason=stop_reason,
                created_at=now_iso,
            )
            can_resume = not should_stop
            terminal_reason = stop_reason

        return HitlProcessOutcome(
            session_id=session_id,
            step_id=step_id,
            total_calls=total_calls,
            confirmed_count=confirmed_count,
            denied_count=denied_count,
            all_denied=all_denied,
            tool_result_events=tool_result_events,
            all_tools_denied_event=all_tools_denied_event,
            can_resume=can_resume,
            terminal_reason=terminal_reason,
        )
