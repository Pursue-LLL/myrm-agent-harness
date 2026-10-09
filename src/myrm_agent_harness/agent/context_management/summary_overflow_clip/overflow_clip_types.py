"""Contracts and data models for summary call context overflow tail clipping and single-retry guard.

[INPUT]
- None (pure domain types and enum contracts).

[OUTPUT]
- Exports data contracts for clipping strategies, tail clip actions,
  summary retry verdicts, clip outcomes, and configuration models.

[POS]
- Sub-package: myrm_agent_harness.agent.context_management.summary_overflow_clip
- Module: overflow_clip_types.py
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Optional, Sequence


class ClipStrategyKind(str, Enum):
    """Categorization of clipping strategies applied to bloated trailing tool results."""

    READ_FILE_HEAD_SLICE = "read_file_head_slice"
    OFFLOAD_STUB_REPLACE = "offload_stub_replace"
    UNTOUCHED = "untouched"


class SummaryRetryVerdict(str, Enum):
    """Verdict on whether a clipped summary request is eligible for a single smaller retry."""

    PERMITTED_ONCE = "permitted_once"
    RETRY_EXHAUSTED = "retry_exhausted"
    IRREDUCIBLE_OVERFLOW = "irreducible_overflow"


@dataclass(frozen=True)
class OverflowClipAction:
    """Action recorded for a specific message during tail clipping."""

    message_index: int
    tool_name: Optional[str]
    strategy_applied: ClipStrategyKind
    original_characters: int
    clipped_characters: int
    estimated_saved_tokens: int


@dataclass(frozen=True)
class OverflowClipOutcome:
    """Outcome of attempting tail clipping on conversation turns intended for summarization."""

    total_messages_clipped: int
    total_tokens_saved: int
    is_strictly_reduced: bool
    actions: Sequence[OverflowClipAction]
    clipped_messages: Sequence[Mapping[str, str]]
    diagnostic_summary: str


@dataclass(frozen=True)
class SummaryOverflowClipConfig:
    """Configuration options governing tail clipping thresholds and single-retry latching."""

    read_file_max_head_lines: int = 40
    tool_stub_max_chars: int = 120
    min_tokens_saved_to_justify_retry: int = 250
    max_summary_retries: int = 1
    read_file_tool_identifiers: Sequence[str] = (
        "read_file",
        "view_file",
        "fetch_file",
        "file_reader",
    )
