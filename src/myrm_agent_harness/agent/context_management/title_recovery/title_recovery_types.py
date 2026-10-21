"""Domain contracts and types for invalid LLM generated title recovery.

[INPUT]
- None (pure domain contracts and data models).

[OUTPUT]
- Exports InvalidTitleReason, TitleValidationResult, TitleRecoveryState,
  TitleRecoveryVerdict, and TitleRecoveryConfig.

[POS]
- Sub-package: myrm_agent_harness.agent.context_management.title_recovery
- Module: title_recovery_types.py
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Sequence, Tuple


class InvalidTitleReason(str, Enum):
    """Specific structural defect categorizing an unviable generated title."""

    VALID = "valid"
    COT_LEAK = "cot_leak"
    OPTION_MENU = "option_menu"
    FIRST_PERSON_PROSE = "first_person_prose"
    CODE_BLOCK_WRAP = "code_block_wrap"
    PUNCTUATION_OR_GARBAGE = "punctuation_or_garbage"
    LENGTH_OUT_OF_BOUNDS = "length_out_of_bounds"
    EMPTY_OR_WHITESPACE = "empty_or_whitespace"


class TitleRecoveryVerdict(str, Enum):
    """Decision produced by the provisional title retry gate."""

    ACCEPTED_CLEAN = "accepted_clean"
    RETRY_LATER_PROVISIONAL = "retry_later_provisional"
    FALLBACK_FINALIZED = "fallback_finalized"


@dataclass(frozen=True)
class TitleValidationResult:
    """Outcome of validating a candidate title string against taxonomy rules."""

    is_valid: bool
    cleaned_title: str
    reasons: Tuple[InvalidTitleReason, ...] = field(default_factory=tuple)
    diagnostic_details: str = ""


@dataclass(frozen=True)
class TitleRecoveryConfig:
    """Configuration governing validation thresholds and retry limits."""

    min_length: int = 2
    max_length: int = 50
    max_recovery_exchanges: int = 3
    fallback_preview_length: int = 20
    strip_title_prefixes: Tuple[str, ...] = (
        "title:",
        "标题:",
        "chat title:",
        "conversation title:",
        "topic:",
    )


@dataclass
class TitleRecoveryState:
    """Tracks session-scoped title generation attempts and latching state."""

    session_id: str
    exchange_count: int = 0
    is_finalized: bool = False
    current_title: str = "Untitled Chat"
    history_verdicts: list[TitleRecoveryVerdict] = field(default_factory=list)
