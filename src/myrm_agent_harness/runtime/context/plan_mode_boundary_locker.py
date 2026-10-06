"""Interactive plan mode pre-execution review and state boundary locker.

Provides read-only boundary enforcement for Claude-Code-style Plan Mode.
In Plan Mode, write/destructive tools are physically stripped and intercepted at runtime,
forcing the agent into a pure observational analysis state to formulate a structured
Implementation Plan. Upon user review and approval, transitions atomically to Act Mode
with the approved plan injected as an immutable execution constraint.

[INPUT]
- enum::Enum, dataclasses::dataclass, typing (POS: Standard library)

[OUTPUT]
- ExecutionMode: Enum representing PLAN vs ACT mode
- ImplementationPlanContract: Strongly typed structured plan contract
- is_read_only_tool: Deterministic tool classification function
- filter_tools_for_mode: Static tool exposure filter for LLM binding
- PlanModeBoundaryLocker: State machine and runtime interceptor

[POS]
Runtime context layer boundary locking and plan review governance component.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

# Built-in read-only search/inspection tools allowed during Plan Mode
_READ_ONLY_TOOL_PATTERNS = frozenset(
    {
        "view",
        "read",
        "grep",
        "glob",
        "find",
        "search",
        "inspect",
        "cat",
        "head",
        "tail",
        "list",
        "fetch",
        "status",
        "query",
        "retrieve",
        "get",
    }
)

# Explicit dangerous/write action keywords strictly forbidden during Plan Mode
_WRITE_ACTION_PATTERNS = frozenset(
    {
        "write",
        "edit",
        "replace",
        "modify",
        "create",
        "save",
        "delete",
        "remove",
        "patch",
        "update",
        "insert",
        "execute",
        "run_command",
        "bash",
        "shell",
    }
)


class ExecutionMode(StrEnum):
    """Execution mode of the agent."""

    PLAN = "plan"
    ACT = "act"


def is_read_only_tool(tool_name: str) -> bool:
    """Determine whether a tool is strictly read-only for Plan Mode.

    A tool is considered read-only if it matches read patterns AND does NOT match
    write/destructive execution patterns.
    """
    clean_name = tool_name.lower().strip()
    if not clean_name:
        return False

    has_write = any(w in clean_name for w in _WRITE_ACTION_PATTERNS)
    if has_write:
        return False

    has_read = any(r in clean_name for r in _READ_ONLY_TOOL_PATTERNS)
    return has_read


def filter_tools_for_mode(
    tools: Sequence[object],
    mode: ExecutionMode,
) -> list[object]:
    """Filter tools exposed to LLM Function Calling based on active mode.

    In Plan Mode, all write/mutating tools are stripped out to guarantee
    zero unintended modifications at the protocol level.
    """
    if mode == ExecutionMode.ACT:
        return list(tools)

    filtered: list[object] = []
    for tool in tools:
        name = getattr(tool, "name", None) or getattr(tool, "__name__", "")
        if isinstance(name, str) and is_read_only_tool(name):
            filtered.append(tool)

    return filtered


@dataclass(frozen=True)
class ImplementationPlanContract:
    """Strongly typed structured implementation plan formulated in Plan Mode."""

    title: str
    summary: str
    steps: list[dict[str, str]] = field(default_factory=list)
    affected_files: list[str] = field(default_factory=list)
    risks_and_mitigations: list[str] = field(default_factory=list)
    approved: bool = False
    review_notes: str = ""

    def to_dict(self) -> dict[str, object]:
        """Convert plan to serializable dictionary."""
        return asdict(self)

    def to_json(self) -> str:
        """Serialize plan to formatted JSON."""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def to_markdown(self) -> str:
        """Render plan into a structured review card."""
        lines: list[str] = [
            f"# Implementation Plan: {self.title}",
            f"**Summary**: {self.summary}",
            "",
            "## Execution Steps:",
        ]
        for s in self.steps:
            step_id = s.get("id", "step")
            desc = s.get("description", "")
            verify = s.get("verification", "")
            verify_str = f" [Verify: {verify}]" if verify else ""
            lines.append(f"{step_id}. {desc}{verify_str}")

        if self.affected_files:
            lines.append("\n## Affected / Targeted Files:")
            for f in self.affected_files:
                lines.append(f"- `{f}`")

        if self.risks_and_mitigations:
            lines.append("\n## Risks & Mitigations:")
            for r in self.risks_and_mitigations:
                lines.append(f"- {r}")

        status_str = " APPROVED" if self.approved else " PENDING USER REVIEW"
        lines.append(f"\n**Status**: {status_str}")
        if self.review_notes:
            lines.append(f"**Review Notes**: {self.review_notes}")

        return "\n".join(lines)


class PlanModeBoundaryLocker:
    """State boundary locker and runtime interceptor for Plan Mode vs Act Mode."""

    def __init__(self, initial_mode: ExecutionMode = ExecutionMode.PLAN) -> None:
        self._mode = initial_mode
        self._current_plan: ImplementationPlanContract | None = None

    @property
    def current_mode(self) -> ExecutionMode:
        """Return the active execution mode."""
        return self._mode

    @property
    def current_plan(self) -> ImplementationPlanContract | None:
        """Return the currently formulated plan, if any."""
        return self._current_plan

    def enter_plan_mode(self) -> None:
        """Switch to Plan Mode and reset unapproved state."""
        self._mode = ExecutionMode.PLAN
        if self._current_plan is not None and not self._current_plan.approved:
            self._current_plan = None

    def submit_plan(self, plan: ImplementationPlanContract) -> None:
        """Submit a newly formulated implementation plan for user review."""
        self._current_plan = plan

    def intercept_tool_call(
        self,
        tool_name: str,
        args: dict[str, object] | None = None,
    ) -> tuple[bool, str]:
        """Intercept tool call at runtime (fail-closed guard).

        Returns:
            (is_blocked, message)
            If is_blocked is True, the tool call must NOT be executed.
        """
        _ = args
        if self._mode == ExecutionMode.ACT:
            return False, ""

        if not is_read_only_tool(tool_name):
            msg = (
                f"PlanModeWriteBlocked: Write or mutating action '{tool_name}' is forbidden in Plan Mode. "
                "The agent is currently in read-only observation mode. "
                "Please formulate and submit an ImplementationPlanContract for user review first."
            )
            return True, msg

        return False, ""

    def approve_and_transition_to_act(self, review_notes: str = "") -> str:
        """Approve current plan and atomically transition to Act Mode.

        Returns:
            Approved Plan Directive string to be injected into LLM context.
        """
        if self._current_plan is None:
            # Create a default approved plan if none was explicitly submitted
            self._current_plan = ImplementationPlanContract(
                title="Direct Action Plan",
                summary="User approved direct transition to Act Mode without explicit plan details.",
                approved=True,
                review_notes=review_notes,
            )
        else:
            self._current_plan = ImplementationPlanContract(
                title=self._current_plan.title,
                summary=self._current_plan.summary,
                steps=self._current_plan.steps,
                affected_files=self._current_plan.affected_files,
                risks_and_mitigations=self._current_plan.risks_and_mitigations,
                approved=True,
                review_notes=review_notes or self._current_plan.review_notes,
            )

        self._mode = ExecutionMode.ACT

        directive_lines = [
            "<approved-implementation-plan>",
            "[SYSTEM DIRECTIVE: The user has formally APPROVED the following implementation plan.]",
            "[You are now in ACT MODE with full write capabilities. Execute strictly following this plan.]",
            "",
            self._current_plan.to_markdown(),
            "</approved-implementation-plan>",
        ]
        return "\n".join(directive_lines)
