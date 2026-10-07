"""Types and schemas for interactive mini-survey cards and rich deliverable document streamout.

[INPUT]
Survey field definitions, user option selections, slider weights, and requirement manifests.

[OUTPUT]
Type-safe representations of declarative survey schemas, validated submissions,
and structured multi-platform deliverable document envelopes.

[POS]
Core protocol benchmarked against Doubao Work creative director interactive mini-surveys and Lark docs.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

SurveyFieldType = Literal["single_select", "multi_select", "slider", "text_input"]


class SurveyValidationStatus(StrEnum):
    """Validation outcome of a user survey submission."""
    VALID = "valid"
    MISSING_REQUIRED_FIELD = "missing_required_field"
    INVALID_OPTION = "invalid_option"
    OUT_OF_BOUNDS = "out_of_bounds"


@dataclass(frozen=True)
class SurveyFieldOption:
    """Selectable option item for single or multi-select survey fields."""
    id: str
    label: str
    description: str | None = None
    is_recommended: bool = False


@dataclass(frozen=True)
class SurveyFieldSpec:
    """Specification of an interactive input control in the survey card."""
    field_id: str
    label: str
    field_type: SurveyFieldType
    required: bool = True
    options: tuple[SurveyFieldOption, ...] = ()
    min_value: float | None = None
    max_value: float | None = None
    step: float | None = None
    default_value: str | tuple[str, ...] | float | None = None
    placeholder: str | None = None


@dataclass(frozen=True)
class InteractiveSurveyCardPayload:
    """Declarative interactive survey card payload dispatched to frontend/desktop clients."""
    survey_id: str
    title: str
    description: str
    fields: tuple[SurveyFieldSpec, ...]
    submit_button_label: str = "确认提交并启动"
    dispatched_at_utc: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )


@dataclass(frozen=True)
class SurveyResponseSubmission:
    """Submitted values payload from the client upon user clicking submit."""
    survey_id: str
    answers: dict[str, str | tuple[str, ...] | float]
    submitted_at_utc: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )


@dataclass(frozen=True)
class SurveyValidationResult:
    """Verification outcome of user survey response submission."""
    is_valid: bool
    status: SurveyValidationStatus
    compiled_manifest: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class RichDeliverableDocument:
    """Structured deliverable document directly exportable to Lark/Notion/Word."""
    document_id: str
    title: str
    author: str
    summary: str
    markdown_content: str
    tags: tuple[str, ...] = ()
    created_at_utc: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )
