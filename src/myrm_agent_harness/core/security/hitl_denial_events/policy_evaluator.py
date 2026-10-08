"""Policy evaluation logic for all-tools-denied scenarios.

[INPUT]
- Collection of denied tool calls and policy configurations.

[OUTPUT]
- Policy evaluation result determining whether the agent should halt or resume.

[POS]
- Decision component configuring whether a full denial terminates the loop
  or feeds denial reasons back to the model for another reasoning cycle.
"""

from __future__ import annotations

from collections.abc import Sequence

from myrm_agent_harness.core.security.hitl_denial_events.types import (
    AllToolsDeniedPolicy,
    ToolUseBlock,
)


class AllToolsDeniedPolicyEvaluator:
    """Evaluates whether an all-tools-denied step should halt or resume."""

    def __init__(
        self,
        default_policy: AllToolsDeniedPolicy = AllToolsDeniedPolicy.HALT,
        strict_halt_tools: Sequence[str] | None = None,
    ) -> None:
        """Initialize policy evaluator.

        Args:
            default_policy: Default action when all tools are denied.
            strict_halt_tools: Tool names that unconditionally force HALT if denied.
        """
        self._default_policy = default_policy
        self._strict_halt_tools = set(strict_halt_tools or [])

    def evaluate(
        self,
        denied_tools: Sequence[ToolUseBlock],
        explicit_policy: AllToolsDeniedPolicy | None = None,
    ) -> tuple[AllToolsDeniedPolicy, bool, str | None]:
        """Determine policy and stop verdict.

        Args:
            denied_tools: List of tool calls that were denied.
            explicit_policy: Optional override requested for this evaluation.

        Returns:
            Tuple of (effective_policy, should_stop, stop_reason).
        """
        # If any strictly guarded tool was denied, unconditionally force HALT
        for tool in denied_tools:
            if tool.name in self._strict_halt_tools:
                return (
                    AllToolsDeniedPolicy.HALT,
                    True,
                    f"ALL_TOOLS_DENIED_CRITICAL_TOOL_{tool.name.upper()}",
                )

        target_policy = explicit_policy or self._default_policy
        if target_policy == AllToolsDeniedPolicy.HALT:
            return (AllToolsDeniedPolicy.HALT, True, "ALL_TOOLS_DENIED")

        return (AllToolsDeniedPolicy.RESUME_WITH_FEEDBACK, False, None)
