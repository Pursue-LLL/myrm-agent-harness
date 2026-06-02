"""Execution Policy and Approval Contract.

[INPUT]

[OUTPUT]
- ExecutionPolicy: Enum for execution policies (allow, require_approval, deny)
- ApprovalContract: Pydantic model for dynamic approval details
- suspend_execution: Function that yields an interrupt using LangGraph

[POS]
Execution policy and suspension abstraction. Defines low-level policy enums and interception contract structures.

"""

from enum import StrEnum
from typing import Any, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ExecutionPolicy(StrEnum):
    """Granular execution policies for actions (tool calls, memory mutations)."""

    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    DENY = "deny"


class ApprovalContract[T](BaseModel):
    """Standardized approval contract generated when execution is suspended."""

    action_type: str = Field(
        ...,
        description="The type of action being intercepted (e.g., 'memory_mutation', 'skill_patch', 'shell_command')",
    )
    payload: T = Field(..., description="The structured data required for the action")
    reason: str = Field(..., description="Why this action requires approval")
    severity: str = Field(default="warning", description="Severity level: info, warning, critical")


def suspend_execution(contract: ApprovalContract[Any]) -> Any:
    """Suspend execution and return the approval decision once resumed.

    Under the hood, this calls LangGraph's `interrupt` with the serialized contract.
    When the graph is resumed (via Command(resume="approve" | "deny")), this
    function returns the decision.

    Args:
        contract: The approval contract payload

    Returns:
        The decision payload injected from the client (e.g., "approve" or {"decision": "approve", "payload": ...})
    """
    from langgraph.types import interrupt

    return interrupt(contract.model_dump())
