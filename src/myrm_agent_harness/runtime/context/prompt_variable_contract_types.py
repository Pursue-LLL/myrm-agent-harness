"""Types and schema definitions for prompt template variable contracts and pre-flight validation.

[INPUT]
Variable contract definitions, incoming dynamic parameter mappings, and template placeholder bindings.

[OUTPUT]
Type-safe schemas, validation exception types, and rendered deterministic template payloads.

[POS]
Item 121 in topic_06 roadmap: pre-flight assertion against variable-induced prefix cache jitter.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class VariableDataType(StrEnum):
    """Supported strongly typed data types for prompt template variables."""
    STRING = "string"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    PATH = "path"
    ENUM = "enum"


@dataclass(frozen=True)
class PromptVariableDefinition:
    """Strongly typed contract for an individual prompt variable."""
    var_name: str
    data_type: VariableDataType
    required: bool = True
    default_value: str | int | bool | None = None
    allowed_values: tuple[str, ...] | None = None
    regex_pattern: str | None = None
    description: str = ""


class PromptVariableMissingError(ValueError):
    """Raised when a required template variable is missing or empty before model dispatch."""


class PromptVariableValidationError(ValueError):
    """Raised when a template variable violates its declared type, enum, or regex constraint."""


@dataclass(frozen=True)
class PromptTemplateRenderResult:
    """Outcome of validating and rendering a prompt template with bound parameters."""
    rendered_content: str
    variables_applied: dict[str, str]
    sha256_hash: str
    render_duration_ms: float
    rendered_at_utc: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )


@dataclass(frozen=True)
class PromptContractSchemaInspectionReport:
    """Pre-flight inspection report comparing template placeholders with declared contracts."""
    contract_name: str
    is_fully_bound: bool
    declared_variables: tuple[str, ...]
    template_placeholders: tuple[str, ...]
    missing_declarations: tuple[str, ...]
    unused_declarations: tuple[str, ...]
