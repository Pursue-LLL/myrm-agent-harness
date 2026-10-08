"""Domain contracts and data models for tri-tier response verbosity and dynamic density tuning.

[INPUT]
- None (Self-contained domain definitions).

[OUTPUT]
- ResponseVerbosityLevel: Tri-tier density enum (LOW, MEDIUM, HIGH).
- VerbositySource: Provenance of the active verbosity selection.
- VerbosityBudgetConfig: Budget limits and default configurations.
- VerbosityContextBundle: Bound instructions, token caps, and resolution provenance.
- DehydratedSummary: Extracted concise TL;DR digest from verbose output.

[POS]
Domain contract layer for Item 311 TriTierResponseVerbosityControlAndDynamicDensityTunerSuite.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Sequence


class ResponseVerbosityLevel(str, Enum):
    """Tri-tier density level controlling response length and detail."""

    LOW = "low"          # ⚡ 极简: Direct conclusions/code only, no fluff (max ~512 tokens)
    MEDIUM = "medium"    # ⚖️ 均衡: Standard engineering balanced response (default)
    HIGH = "high"        # 📖 详尽: In-depth rationale, architecture trade-offs, verbose comments


class VerbositySource(str, Enum):
    """Origin of the resolved verbosity level in the cascade."""

    TURN_OVERRIDE = "turn_override"        # Temporary single-turn toggle from composer
    SESSION_PREFERENCE = "session_pref"   # Sticky preference chosen in active chat session
    PROFILE_DEFAULT = "profile_default"   # Agent profile preset (e.g. Auditor=Low, Tutor=High)
    SYSTEM_DEFAULT = "system_default"     # Framework global default (Medium)


@dataclass(frozen=True)
class VerbosityBudgetConfig:
    """Token budget limits and discipline constraints per verbosity tier."""

    low_max_tokens: int = 512
    medium_max_tokens: int = 2048
    high_max_tokens: int = 8192
    default_level: ResponseVerbosityLevel = ResponseVerbosityLevel.MEDIUM
    enforce_token_budget_clamping: bool = True
    inject_system_discipline_prompt: bool = True


@dataclass(frozen=True)
class VerbosityContextBundle:
    """Resolved verbosity decision bundle bound to a generation request."""

    level: ResponseVerbosityLevel
    source: VerbositySource
    prompt_discipline_instruction: str
    recommended_max_tokens: int
    recommended_presence_penalty: float = 0.0


@dataclass(frozen=True)
class DehydratedSummary:
    """Structured concise summary extracted from post-generation verbose output."""

    original_length_chars: int
    dehydrated_length_chars: int
    tldr_text: str
    key_takeaways: Sequence[str] = field(default_factory=tuple)
    compression_ratio: float = 1.0
