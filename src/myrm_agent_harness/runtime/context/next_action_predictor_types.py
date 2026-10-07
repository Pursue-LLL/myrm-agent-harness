"""Types and data contracts for In-Context Next Action and Question Predictor.

Provides domain models, structured action chip definitions, turn execution
artifact representations, and configuration models for proactive suggestions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ActionIntentType(StrEnum):
    """Categorized intent of a predicted proactive action."""

    TEST_VERIFICATION = "test_verification"
    CODE_REVIEW = "code_review"
    BUG_FIX = "bug_fix"
    DOCUMENTATION = "documentation"
    BUILD_DEPLOY = "build_deploy"
    DEEPEN_INQUIRY = "deepen_inquiry"
    CUSTOM_ACTION = "custom_action"


@dataclass(frozen=True, slots=True)
class PredictedActionChip:
    """Action chip suggested for user click-to-run."""

    chip_id: str
    intent: ActionIntentType
    label: str
    prompt: str
    target_resource: str | None = None
    confidence: float = 0.8
    icon_hint: str = "sparkles"
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TurnExecutionArtifact:
    """Execution artifacts observed during the most recent agent turn."""

    modified_files: list[str] = field(default_factory=list)
    executed_commands: list[str] = field(default_factory=list)
    test_passed: bool | None = None
    has_error: bool = False
    error_excerpt: str | None = None
    active_task_name: str | None = None


@dataclass(frozen=True, slots=True)
class PredictionContextInput:
    """Aggregated context consumed by the action predictor."""

    session_id: str
    last_user_query: str
    last_assistant_reply: str
    recent_turn_count: int = 1
    artifact: TurnExecutionArtifact | None = None
    history_summary: str | None = None


@dataclass(frozen=True, slots=True)
class NextActionPredictionReport:
    """Result payload delivered by the prediction engine."""

    session_id: str
    chips: list[PredictedActionChip]
    engine_source: str
    duration_ms: float
    has_test_recommendation: bool
    fallback_used: bool = False


@dataclass(frozen=True, slots=True)
class NextActionPredictorConfig:
    """Operational settings controlling prediction limits and heuristics."""

    max_chips: int = 4
    min_confidence: float = 0.5
    enable_heuristic: bool = True
    deduplicate_by_intent: bool = False
