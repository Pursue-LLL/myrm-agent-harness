"""Data models and type definitions for onboarding insight sampling and reporting.

[INPUT]
- typing: NamedTuple, Literal, Optional, List, Dict
- dataclasses: dataclass, field

[OUTPUT]
- OnboardingSampleOptions: Configuration options for conversation sampling.
- SampledTurnMessage: Single turn message extracted from historical conversation logs.
- OnboardingConversationWindow: Sliding window of sampled messages from one conversation.
- InsightExtractedFact: Structured preference, lesson, or goal extracted from history.
- FirstEncounterReport: Complete first-encounter insight report presented to user.

[POS]
Harness framework core data contracts for multi-source historical conversation sampling,
local zero-leakage secret scrubbing, and first-encounter insight reporting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class OnboardingSampleOptions:
    """Configuration options for historical conversation sliding window sampling."""

    max_session_files: int = 6
    first_conversation_turns: int = 2
    last_conversation_turns: int = 12
    max_user_chars: int = 1200
    max_assistant_chars: int = 2000
    max_tool_chars: int = 400
    max_window_chars: int = 24000
    strip_media_payloads: bool = True
    enable_entropy_inspection: bool = True


@dataclass(frozen=True)
class SampledTurnMessage:
    """Individual message extracted from a source agent conversation turn."""

    source_id: str
    conversation_id: str
    message_id: str
    role: Literal["user", "assistant", "tool", "system"]
    text: str
    created_at: str
    workspace_path: str | None = None


@dataclass
class OnboardingConversationWindow:
    """Aggregated window of sampled turns for a single conversation file."""

    source_id: str
    conversation_id: str
    display_name: str
    file_path: str
    messages: list[SampledTurnMessage] = field(default_factory=list)
    total_chars: int = 0
    truncated: bool = False
    error: str | None = None


@dataclass(frozen=True)
class InsightExtractedFact:
    """Extracted insight item categorized into tech stack, lesson, or active goal."""

    fact_id: str
    category: Literal["tech_stack_preference", "hard_learned_lesson", "active_project_goal"]
    summary: str
    source_agent: str
    confidence: float
    fingerprint: str
    origin_conversation_id: str
    raw_quote: str = ""


@dataclass
class FirstEncounterReport:
    """Full onboarding insight report generated from multi-source historical sessions."""

    report_id: str
    generated_at: str
    probed_sources: list[str] = field(default_factory=list)
    scanned_session_count: int = 0
    total_messages_sampled: int = 0
    facts: list[InsightExtractedFact] = field(default_factory=list)
    scrubbed_secret_count: int = 0
    warnings: list[str] = field(default_factory=list)
