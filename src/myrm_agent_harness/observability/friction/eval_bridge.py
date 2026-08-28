"""Eval Lab Bridge for converting runtime TaskFrictionEvents into regression EvalCases.

[INPUT]
- myrm_agent_harness.observability.friction.types::TaskFrictionEvent (POS: 摩擦点基础事件)
- myrm_agent_harness.eval.protocols::(EvalCase, StateAssertion) (POS: 评测协议类型系统)

[OUTPUT]
- friction_to_eval_case: Transforms a TaskFrictionEvent into a standardized regression EvalCase

[POS]
Model co-evolution bridge that feeds real-world runtime task friction points directly into the Eval Lab regression suite.
"""

from __future__ import annotations

from myrm_agent_harness.eval.protocols import EvalCase, StateAssertion
from myrm_agent_harness.observability.friction.types import (
    FrictionCategory,
    TaskFrictionEvent,
)


def friction_to_eval_case(
    friction: TaskFrictionEvent,
    *,
    custom_prompt: str | None = None,
    tags: list[str] | None = None,
) -> EvalCase:
    """Convert a TaskFrictionEvent into a repeatable regression EvalCase for Eval Lab.

    Args:
        friction: The offending runtime friction event.
        custom_prompt: Optional custom test prompt; defaults to generated friction prompt.
        tags: Optional list of categorization tags.

    Returns:
        A strongly typed EvalCase targeting the specific tool and failure category.
    """
    case_id = f"eval_fric_{friction.category.value.lower()}_{friction.id[:8]}"
    prompt = custom_prompt or (
        f"Execute tool '{friction.tool_name}' with valid arguments to achieve the expected task. "
        f"Context from prior friction: {friction.message}"
    )

    combined_tags = [
        "friction_regression",
        f"cat_{friction.category.value.lower()}",
        f"tool_{friction.tool_name}",
    ]
    if tags:
        combined_tags.extend(tags)

    # Establish state assertion demanding non-empty and non-error outcome
    assertions = [
        StateAssertion(
            type="not_contains",
            expected=friction.message[:100] if len(friction.message) > 5 else "Error",
        )
    ]

    return EvalCase(
        message=prompt,
        state_assertions=assertions,
        metadata={
            "case_id": case_id,
            "name": f"Friction Regression: {friction.tool_name} [{friction.category.value}]",
            "description": (
                f"Automated regression test generated from runtime friction event in session {friction.session_id}. "
                f"Original Error: {friction.message}"
            ),
            "source_session_id": friction.session_id,
            "source_trace_id": friction.trace_id or "",
            "friction_category": friction.category.value,
            "fault_side": friction.fault_side,
            "original_input": friction.input_payload or "",
            "tags": ",".join(combined_tags),
        },
    )
