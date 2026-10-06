"""Hidden Goal & Rubric Context Preamble Injection Engine (Pi Harness v2 Item 28).

Implements zero-round-trip goal and acceptance criteria context preambles:
1. Zero-Round-Trip Goal Ingestion:
   Automatically supplies active objectives and rubric acceptance criteria as internal model
   preamble context, eliminating costly `get_goal` / `get_rubric` turn-1 tool calls and latency.
2. User-Hidden Transcript Isolation:
   Preambles travel with `lc_source="goal_state"` and `is_hidden_preamble=True` metadata, ensuring they
   are hidden from user-visible transcripts, thread titles, and UI chat bubbles.
3. Superseded Replacement & Dynamic Alignment:
   When goal objectives or rubrics change mid-session, supersedes previous notices and pins current state.
4. Prompt Safety & Context Boundary Safeguard:
   Escapes embedded objectives and labels them explicitly as context data to prevent injection exploits.

[INPUT]
- context: GoalRubricContext
- messages: Sequence[BaseMessage]
- policy: PreambleInjectionPolicy

[OUTPUT]
- GoalStatus
- RubricSource
- GoalRubricContext
- PreambleInjectionPolicy
- HiddenGoalRubricPreamble

[POS]
Harness runtime context layer. Delivers instant turn-1 goal grounding with zero tool-call round-trips.
"""

from __future__ import annotations

import hashlib
import html
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage


class GoalStatus(StrEnum):
    """Lifecycle status of the active goal."""

    ACTIVE = "active"
    PAUSED = "paused"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


class RubricSource(StrEnum):
    """Provenance of the rubric criteria."""

    GOAL = "goal"
    STICKY = "sticky"
    INVOCATION = "invocation"


@dataclass(slots=True, frozen=True)
class GoalRubricContext:
    """Current active objective and acceptance rubric state."""

    goal_id: str
    objective: str
    criteria: str
    status: GoalStatus = GoalStatus.ACTIVE
    status_note: str = ""
    rubric_source: RubricSource = RubricSource.GOAL
    schema_version: int = 1

    @property
    def fingerprint(self) -> str:
        """Deterministic fingerprint of active goal and rubric parameters."""
        raw = f"{self.goal_id}:{self.objective}:{self.criteria}:{self.status.value}:{self.status_note}:{self.rubric_source.value}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


@dataclass(slots=True, frozen=True)
class PreambleInjectionPolicy:
    """Policy governing hidden preamble injection and user transcript isolation."""

    hide_from_user_transcript: bool = True
    lc_source_tag: str = "goal_state"
    superseded_source_tag: str = "goal_state_superseded"


class HiddenGoalRubricPreamble:
    """Engine for formatting, injecting, and filtering hidden goal/rubric preambles."""

    @staticmethod
    def format_preamble_block(context: GoalRubricContext) -> str:
        """Render escaped, structured goal-state context notice for the model."""
        escaped_objective = html.escape(context.objective.strip())
        escaped_criteria = html.escape(context.criteria.strip())
        status_line = f"Status: {context.status.value.upper()}"
        if context.status_note:
            status_line += f" ({html.escape(context.status_note.strip())})"

        return (
            "<!-- INTERNAL GOAL & ACCEPTANCE RUBRIC (Supplied automatically by Harness) -->\n"
            f"<goal_objective>\n{escaped_objective}\n</goal_objective>\n"
            f"<acceptance_criteria source='{context.rubric_source.value}'>\n{escaped_criteria}\n</acceptance_criteria>\n"
            f"<goal_status>\n{status_line}\n</goal_status>\n"
            "Treat the above objective and criteria as active task context. Begin execution directly "
            "without invoking `get_goal` or `get_rubric`.\n"
            "<!-- END INTERNAL GOAL & RUBRIC -->"
        )

    @classmethod
    def is_hidden_goal_message(cls, message: BaseMessage, policy: PreambleInjectionPolicy | None = None) -> bool:
        """Check if message is a framework-owned hidden goal context notice."""
        active_policy = policy or PreambleInjectionPolicy()
        kwargs = getattr(message, "additional_kwargs", {}) or {}
        if kwargs.get("is_hidden_preamble") is True:
            return True
        lc_source = kwargs.get("lc_source") or getattr(message, "lc_source", None)
        return lc_source in (active_policy.lc_source_tag, active_policy.superseded_source_tag)

    @classmethod
    def inject_preamble_message(
        cls,
        messages: Sequence[BaseMessage],
        context: GoalRubricContext,
        policy: PreambleInjectionPolicy | None = None,
    ) -> list[BaseMessage]:
        """Inject current goal context message, superseding any prior notices in place."""
        active_policy = policy or PreambleInjectionPolicy()
        formatted_content = cls.format_preamble_block(context)

        new_notice = HumanMessage(
            content=formatted_content,
            additional_kwargs={
                "lc_source": active_policy.lc_source_tag,
                "is_hidden_preamble": True,
                "goal_id": context.goal_id,
                "goal_fingerprint": context.fingerprint,
                "schema_version": context.schema_version,
            },
        )

        output: list[BaseMessage] = []
        replaced_existing = False

        for msg in messages:
            if cls.is_hidden_goal_message(msg, active_policy):
                # Mark previous goal notices as superseded
                superseded_kwargs = dict(getattr(msg, "additional_kwargs", {}) or {})
                superseded_kwargs["lc_source"] = active_policy.superseded_source_tag
                superseded_msg = HumanMessage(
                    content="<!-- Stale goal context superseded by latest update -->",
                    additional_kwargs=superseded_kwargs,
                )
                output.append(superseded_msg)
                replaced_existing = True
            else:
                output.append(msg)

        if replaced_existing:
            # Place the fresh notice near the end (before last turn if human, or at tip)
            output.append(new_notice)
            return output

        # If no prior notice existed, inject right after leading SystemMessage(s)
        insert_idx = 0
        while insert_idx < len(output) and isinstance(output[insert_idx], SystemMessage):
            insert_idx += 1

        output.insert(insert_idx, new_notice)
        return output

    @classmethod
    def filter_for_user_transcript(
        cls,
        messages: Sequence[BaseMessage],
        policy: PreambleInjectionPolicy | None = None,
    ) -> list[BaseMessage]:
        """Strip internal hidden goal preambles so user-facing UI / transcript is 100% clean."""
        active_policy = policy or PreambleInjectionPolicy()
        return [msg for msg in messages if not cls.is_hidden_goal_message(msg, active_policy)]
