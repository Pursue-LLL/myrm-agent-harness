"""Commerce Session Slice & Automated Regression Evaluation Suite.

[INPUT]
- typing::Literal
- pydantic::BaseModel, Field
- myrm_agent_harness.backends.commerce.types::CommerceRole
- myrm_agent_harness.backends.commerce.verticals::VerticalDomain

[OUTPUT]
- SliceStep: Single interaction or tool execution step in a session slice
- CommerceSessionSlice: Full session state slice capturing user-agent interaction & state snapshot
- SliceAssertion: Declarative assertion for regression evaluation
- CommerceSliceEvalCase: Benchmark eval case derived from session slices
- SliceEvalResult: Outcome of slice regression execution
- export_commerce_slice_eval(): Export a session slice into a standardized eval case dictionary
- run_commerce_slice_regression(): Run deterministic regression evaluation against assertions

[POS]
Provides GUI-First session slice capture and automated evaluation generation,
eliminating the need for manual CLI-based eval authoring in transactional commerce.
"""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from typing import Literal
from pydantic import BaseModel, Field

from myrm_agent_harness.backends.commerce.types import CommerceRole
from myrm_agent_harness.backends.commerce.verticals import VerticalDomain

AssertionType = Literal[
    "equals",
    "contains",
    "greater_than_or_equal",
    "less_than_or_equal",
    "not_null",
    "guardrail_passed",
    "guardrail_rejected",
]


class SliceStep(BaseModel):
    """Represents a single step in a conversational commerce session slice."""

    step_index: int
    actor: Literal["user", "assistant", "system", "tool"]
    content: str
    action_type: str | None = None
    action_payload: dict[str, str | int | float | bool | list[str]] = Field(default_factory=dict)


class SliceAssertion(BaseModel):
    """Declarative check verifying commerce invariants during regression."""

    target_path: str
    assertion_type: AssertionType
    expected_value: str | int | float | bool | list[str] | None = None
    description: str = ""


class CommerceSessionSlice(BaseModel):
    """Captures a coherent slice of commercial interaction with state snapshots."""

    slice_id: str
    session_id: str
    domain: VerticalDomain
    role: CommerceRole
    created_at_iso: str
    steps: list[SliceStep] = Field(default_factory=list)
    state_snapshot: dict[str, str | int | float | bool | list[str] | dict[str, str]] = Field(default_factory=dict)
    metadata: dict[str, str] = Field(default_factory=dict)


class CommerceSliceEvalCase(BaseModel):
    """Eval case consumable by benchmark runners and WebUI eval lab."""

    case_id: str
    title: str
    domain: VerticalDomain
    role: CommerceRole
    user_query: str
    context_slice_id: str
    assertions: list[SliceAssertion] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class SliceEvalResult(BaseModel):
    """Result of running a slice regression assertion check."""

    case_id: str
    passed: bool
    total_assertions: int
    passed_assertions: int
    failed_assertions: list[str] = Field(default_factory=list)
    latency_ms: float = 0.0


def export_commerce_slice_eval(
    session_slice: CommerceSessionSlice,
    title: str,
    assertions: list[SliceAssertion],
    tags: list[str] | None = None,
) -> dict[str, str | int | float | bool | list[dict[str, str | int | float | bool | None | list[str]]] | dict[str, str]]:
    """Export a CommerceSessionSlice into a structured slice evaluation dictionary.

    Replaces terminal CLI eval authoring with deterministic JSON structure.
    """
    user_queries = [step.content for step in session_slice.steps if step.actor == "user"]
    primary_query = user_queries[-1] if user_queries else ""

    eval_case = CommerceSliceEvalCase(
        case_id=f"eval_{session_slice.slice_id}",
        title=title,
        domain=session_slice.domain,
        role=session_slice.role,
        user_query=primary_query,
        context_slice_id=session_slice.slice_id,
        assertions=assertions,
        tags=tags or [session_slice.domain, session_slice.role.value],
    )

    return eval_case.model_dump()


def run_commerce_slice_regression(
    eval_case: CommerceSliceEvalCase,
    runtime_state: dict[str, str | int | float | bool | list[str] | dict[str, str]],
) -> SliceEvalResult:
    """Execute assertions against evaluated runtime state."""
    failed_reasons: list[str] = []
    passed_count = 0

    for assertion in eval_case.assertions:
        actual_value = runtime_state.get(assertion.target_path)
        expected = assertion.expected_value
        atype = assertion.assertion_type

        success = False
        if atype == "equals":
            success = actual_value == expected
        elif atype == "contains":
            if isinstance(actual_value, (list, str)) and expected is not None:
                success = str(expected) in str(actual_value)
        elif atype == "greater_than_or_equal":
            if isinstance(actual_value, (int, float)) and isinstance(expected, (int, float)):
                success = actual_value >= expected
        elif atype == "less_than_or_equal":
            if isinstance(actual_value, (int, float)) and isinstance(expected, (int, float)):
                success = actual_value <= expected
        elif atype == "not_null":
            success = actual_value is not None
        elif atype == "guardrail_passed":
            success = actual_value is True or str(actual_value).lower() in ("true", "passed")
        elif atype == "guardrail_rejected":
            success = actual_value is False or str(actual_value).lower() in ("false", "rejected")

        if success:
            passed_count += 1
        else:
            failed_reasons.append(
                f"Assertion failed for '{assertion.target_path}': expected {atype} {expected}, got {actual_value}. ({assertion.description})"
            )

    is_all_passed = len(failed_reasons) == 0
    return SliceEvalResult(
        case_id=eval_case.case_id,
        passed=is_all_passed,
        total_assertions=len(eval_case.assertions),
        passed_assertions=passed_count,
        failed_assertions=failed_reasons,
    )
