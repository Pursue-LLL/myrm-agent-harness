"""Lean Compaction Summary Contract and Prompt Templates.

[INPUT]
- infra.schemas::StructuredSummary (POS: Standard 14-field structured summary DTO)

[OUTPUT]
- LeanStructuredSummary: High-cohesion 4-pillar summary data model
- LEAN_SUMMARY_PROMPT_TEMPLATE: Token-lean prompt template focusing on semantics
- LEAN_SUMMARY_MERGE_PROMPT_TEMPLATE: Incremental lean merge prompt template

[POS]
Harness framework layer context management. Reduces LLM summary payload by 65%+
by offloading deterministic machine symbols to ExactAnchorTable, leaving the LLM
to focus exclusively on user goal, active state, key decisions, and next steps.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from ...infra.schemas import StructuredSummary


class LeanStructuredSummary(BaseModel):
    """High-cohesion 4-pillar lean summary data model."""

    user_goal: str = Field(
        default="",
        description="Core intent and ultimate target requested by the user.",
    )
    active_state: str = Field(
        default="",
        description="Current operational progress and execution state snapshot.",
    )
    key_decisions: list[str] = Field(
        default_factory=list,
        description="Irreversible architectural, design, or algorithmic decisions made.",
    )
    next_steps: list[str] = Field(
        default_factory=list,
        description="Immediate actionable next tasks remaining to complete the goal.",
    )

    def to_structured_summary(self) -> StructuredSummary:
        """Convert to standard StructuredSummary with defensive empty defaults for full compatibility."""
        from ...infra.schemas import StructuredSummary

        return StructuredSummary(
            user_goal=self.user_goal,
            active_state=self.active_state,
            active_task=self.next_steps[0] if self.next_steps else "",
            next_steps=list(self.next_steps),
            key_findings=list(self.key_decisions),
            completed_actions=[],
            errors_and_fixes=[],
            files_modified=[],
            last_action="",
            context_dump_path="",
            constraints_and_preferences=[],
            resolved_questions=[],
            pending_user_asks=[],
            blocked_items=[],
        )

    @classmethod
    def from_structured_summary(cls, summary: StructuredSummary) -> LeanStructuredSummary:
        """Extract high-cohesion lean summary from a full 14-field StructuredSummary."""
        decisions: list[str] = []
        if getattr(summary, "key_findings", None):
            decisions.extend(summary.key_findings[:5])

        steps: list[str] = []
        if getattr(summary, "next_steps", None):
            steps.extend(summary.next_steps[:5])
        elif getattr(summary, "active_task", None) and summary.active_task != "None":
            steps.append(summary.active_task)

        return cls(
            user_goal=getattr(summary, "user_goal", "") or "",
            active_state=getattr(summary, "active_state", "") or "",
            key_decisions=decisions,
            next_steps=steps,
        )


LEAN_SUMMARY_PROMPT_TEMPLATE = """You are a context compaction assistant creating a lean memory checkpoint for another AI assistant.
Your output will be injected as background context into subsequent conversation turns.
Do not answer questions or execute tasks — only output a valid JSON object matching the 4 fields below.

IMPORTANT:
- Output ONLY a valid JSON object matching the schema. No markdown headers, no commentary.
- Write all field values in the same language the user was using in the conversation.
- Machine symbols (exact files, commit hashes, error traces) are handled separately by deterministic anchors; focus strictly on high-level semantic progress.

## Field Instructions
1. user_goal: The user's ultimate core goal in 1-2 concise sentences.
2. active_state: Current operational status snapshot (what has succeeded so far, what is currently running or paused).
3. key_decisions: Critical design, technical, or business decisions established during the dialogue (max 5 items).
4. next_steps: Immediate actionable next tasks to execute (max 5 items, specific and ordered).

## Conversation History
{context}
{budget_hint}"""


LEAN_SUMMARY_MERGE_PROMPT_TEMPLATE = """You are a context compaction assistant updating an existing lean memory checkpoint with recent conversation progress.
Output ONLY a valid JSON object matching the 4 fields below.

IMPORTANT:
- Output ONLY a valid JSON object. No markdown headers, no commentary.
- Write field values in the user's conversation language.
- Merge newly completed items into active_state and update next_steps accordingly.

## Field Instructions
1. user_goal: Preserved or refined core goal.
2. active_state: Updated operational progress incorporating recent actions.
3. key_decisions: Cumulative architectural or technical decisions (max 5 items).
4. next_steps: Updated remaining next steps (max 5 items).

## Existing Summary
{existing_summary}

## Recent Conversation
{context}
{budget_hint}"""
