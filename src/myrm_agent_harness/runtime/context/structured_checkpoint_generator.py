"""Structured checkpoint generator and focus-guided compaction directive pipeline.

Implements the 6-Dimensional Checkpoint Contract (Goal, Constraints & Preferences,
Progress, Key Decisions, Next Steps, Critical Context) combined with deterministic
File I/O state, incremental previous-summary evolution, and focus-guided compaction.

[INPUT]
- langchain_core.messages::BaseMessage
- .file_io_checkpoint_tracker::DeterministicFileIOSummary, extract_deterministic_file_io

[OUTPUT]
- StructuredCheckpointContract: Strongly typed 6-D context checkpoint contract
- compute_summary_max_output_tokens: Bounded output token budget calculator
- build_checkpoint_prompt: Prompt generator supporting previous-summary & additional-focus
- parse_checkpoint_contract: Robust JSON/Text parser into StructuredCheckpointContract

[POS]
Runtime context management checkpoint synthesis layer.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .file_io_checkpoint_tracker import (
    DeterministicFileIOSummary,
    extract_deterministic_file_io,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from langchain_core.messages import BaseMessage


@dataclass(frozen=True)
class StructuredCheckpointContract:
    """Strongly typed 6-Dimensional Checkpoint Contract.

    Fields:
    1. goal: Original core user goal
    2. constraints_and_preferences: Explicit user constraints, rules, style guides
    3. progress: Completed actions, milestones, and unblocked items
    4. key_decisions: Key architecture choices, technical trade-offs, and rationale
    5. next_steps: Planned next actions in concrete executable sequence
    6. critical_context: Crucial identifiers, symbols, env vars, error messages
    7. file_io: Authoritative, immutable file I/O and artifact status
    8. additional_focus: User-specified focus instructions (from /compact <focus>)
    """

    goal: str
    constraints_and_preferences: list[str] = field(default_factory=list)
    progress: list[str] = field(default_factory=list)
    key_decisions: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)
    critical_context: list[str] = field(default_factory=list)
    file_io: DeterministicFileIOSummary = field(default_factory=DeterministicFileIOSummary)
    additional_focus: str = ""

    def to_dict(self) -> dict[str, object]:
        """Convert contract to serializable dictionary."""
        return {
            "goal": self.goal,
            "constraints_and_preferences": self.constraints_and_preferences,
            "progress": self.progress,
            "key_decisions": self.key_decisions,
            "next_steps": self.next_steps,
            "critical_context": self.critical_context,
            "files_read": self.file_io.files_read,
            "files_modified": self.file_io.files_modified,
            "artifacts_created": self.file_io.artifacts_created,
            "additional_focus": self.additional_focus,
        }

    def to_json(self) -> str:
        """Serialize contract to formatted JSON string."""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def to_markdown(self) -> str:
        """Render contract into readable Markdown format for message context."""
        sections: list[str] = [
            "# Context Checkpoint Summary",
            f"**Goal**: {self.goal or 'None'}",
        ]

        if self.additional_focus:
            sections.append(f"**Focused Directive**: {self.additional_focus}")

        if self.constraints_and_preferences:
            sections.append("## Constraints & Preferences")
            for c in self.constraints_and_preferences:
                sections.append(f"- {c}")

        if self.progress:
            sections.append("## Progress & Completed Milestones")
            for p in self.progress:
                sections.append(f"- {p}")

        if self.key_decisions:
            sections.append("## Key Architecture Decisions")
            for d in self.key_decisions:
                sections.append(f"- {d}")

        if self.next_steps:
            sections.append("## Next Steps")
            for s in self.next_steps:
                sections.append(f"- {s}")

        if self.critical_context:
            sections.append("## Critical Technical Context")
            for ctx in self.critical_context:
                sections.append(f"- {ctx}")

        if not self.file_io.is_empty():
            sections.append(self.file_io.to_markdown())

        return "\n".join(sections)


def compute_summary_max_output_tokens(
    reserve_tokens: int = 16384,
    model_max_tokens: int = 4096,
) -> int:
    """Calculate bounded maximum output tokens for compaction summary.

    Formula: min(floor(reserve_tokens * 0.8), model_max_tokens).
    Floor at 512 tokens to guarantee sufficient representation space.
    """
    safe_cap = int(reserve_tokens * 0.8)
    computed = min(safe_cap, model_max_tokens)
    return max(512, computed)


_CHECKPOINT_SCHEMA_PROMPT = """You are an expert context checkpoint architect.
Your task is to summarize prior conversation history into a structured 6-Dimensional Checkpoint.
Output ONLY a valid JSON object matching the schema below:

```json
{
  "goal": "Core objective of the user in one clear sentence",
  "constraints_and_preferences": ["Key constraints, style preferences, prohibitions"],
  "progress": ["Concrete completed actions, resolved subtasks, current milestones"],
  "key_decisions": ["Important architecture decisions, rationale, rejected alternatives"],
  "next_steps": ["Concrete actionable next steps to continue seamlessly"],
  "critical_context": ["Crucial technical entities, symbols, error details, env variables"]
}
```
"""


def build_checkpoint_prompt(
    conversation_text: str,
    previous_summary: StructuredCheckpointContract | None = None,
    additional_focus: str = "",
    file_io_summary: DeterministicFileIOSummary | None = None,
) -> str:
    """Build compaction prompt with incremental evolution and focus guidance."""
    parts: list[str] = [_CHECKPOINT_SCHEMA_PROMPT.strip()]

    # 1. Incremental previous-summary anchor
    if previous_summary is not None:
        parts.append("\n## [PREVIOUS-SUMMARY ANCHOR - INCREMENTAL UPDATE MODE]")
        parts.append(
            "An existing checkpoint is provided below. Do NOT restart from scratch.\n"
            "Preserve foundational goals and decisions, update progress with newly completed milestones,\n"
            "and discard obsolete or completed blockers."
        )
        parts.append(f"```json\n{previous_summary.to_json()}\n```")

    # 2. Focus-guided directive
    clean_focus = additional_focus.strip()
    if clean_focus:
        parts.append(f"\n## [CRITICAL ADDITIONAL FOCUS: \"{clean_focus}\"]")
        parts.append(
            f"The user explicitly specified: \"{clean_focus}\".\n"
            f"You MUST prioritize information, decisions, and progress regarding this focus area,\n"
            "dedicating roughly 60-70% of the summary detail to it without omitting foundational goals."
        )

    # 3. Deterministic file I/O facts (read-only reference)
    if file_io_summary and not file_io_summary.is_empty():
        parts.append("\n## [DETERMINISTIC FILE I/O & ARTIFACT FACTS]")
        parts.append(
            "The system has already deterministically extracted all file read/write operations.\n"
            "You do not need to enumerate individual files in the JSON fields unless relevant to decisions:\n"
            f"{file_io_summary.to_markdown()}"
        )

    # 4. Conversation content to compress
    parts.append("\n## [CONVERSATION CONTENT TO SUMMARIZE]")
    parts.append(conversation_text.strip())

    return "\n\n".join(parts)


def parse_checkpoint_contract(
    raw_response: str,
    file_io: DeterministicFileIOSummary | None = None,
    additional_focus: str = "",
) -> StructuredCheckpointContract:
    """Robustly parse LLM response text into StructuredCheckpointContract."""
    effective_file_io = file_io or DeterministicFileIOSummary()
    cleaned = raw_response.strip()

    # Extract JSON block if wrapped in markdown fences
    json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
    candidate_str = json_match.group(1) if json_match else cleaned

    parsed_dict: dict[str, object] = {}
    try:
        loaded = json.loads(candidate_str)
        if isinstance(loaded, dict):
            parsed_dict = loaded
    except Exception:
        # Fallback: find outer curly braces
        brace_match = re.search(r"(\{.*\})", cleaned, re.DOTALL)
        if brace_match:
            try:
                loaded = json.loads(brace_match.group(1))
                if isinstance(loaded, dict):
                    parsed_dict = loaded
            except Exception:
                pass

    def _as_str(val: object) -> str:
        return str(val).strip() if val is not None else ""

    def _as_list_str(val: object) -> list[str]:
        if isinstance(val, list):
            return [str(item).strip() for item in val if str(item).strip()]
        if isinstance(val, str) and val.strip():
            return [val.strip()]
        return []

    goal = _as_str(parsed_dict.get("goal")) or "Maintain task continuity and complete active requests."
    constraints = _as_list_str(parsed_dict.get("constraints_and_preferences"))
    progress = _as_list_str(parsed_dict.get("progress"))
    decisions = _as_list_str(parsed_dict.get("key_decisions"))
    next_steps = _as_list_str(parsed_dict.get("next_steps"))
    critical_ctx = _as_list_str(parsed_dict.get("critical_context"))

    return StructuredCheckpointContract(
        goal=goal,
        constraints_and_preferences=constraints,
        progress=progress,
        key_decisions=decisions,
        next_steps=next_steps,
        critical_context=critical_ctx,
        file_io=effective_file_io,
        additional_focus=additional_focus,
    )


def create_checkpoint_from_messages(
    messages: Sequence[BaseMessage],
    chat_id: str | None = None,
    previous_summary: StructuredCheckpointContract | None = None,
    additional_focus: str = "",
) -> tuple[str, DeterministicFileIOSummary]:
    """Helper creating both the deterministic file I/O summary and the prompt."""
    file_io = extract_deterministic_file_io(messages, chat_id=chat_id)
    text_content = "\n".join(f"{getattr(m, 'type', type(m).__name__)}: {getattr(m, 'content', '')}" for m in messages)
    prompt = build_checkpoint_prompt(
        conversation_text=text_content,
        previous_summary=previous_summary,
        additional_focus=additional_focus,
        file_io_summary=file_io,
    )
    return prompt, file_io
