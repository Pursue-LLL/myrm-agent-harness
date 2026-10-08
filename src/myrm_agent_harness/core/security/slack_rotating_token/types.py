"""Types and schemas for Slack Rotating Token Classification and Scope Inspection."""

from enum import StrEnum
from pydantic import BaseModel, ConfigDict, Field


class SlackTokenType(StrEnum):
    """Semantic identity associated with a Slack token."""

    BOT = "bot"
    USER = "user"
    REFRESH = "refresh"
    UNKNOWN = "unknown"


class SlackTokenCategory(StrEnum):
    """Lifecycle Category of a Slack token."""

    STATIC = "static"
    ROTATING = "rotating"
    REFRESH = "refresh"
    UNKNOWN = "unknown"


class SlackTokenClassification(BaseModel):
    """Result of classifying a Slack access or refresh token."""

    model_config = ConfigDict(frozen=True)

    token_type: SlackTokenType
    category: SlackTokenCategory
    is_rotating: bool
    prefix_matched: str | None = None
    normalized_token: str
    is_bearer_wrapped: bool = False


class SlackScopeInspection(BaseModel):
    """Resolved OAuth scopes associated with an inspected token and metadata."""

    model_config = ConfigDict(frozen=True)

    token_type: SlackTokenType
    resolved_scopes: list[str] = Field(default_factory=list)
    source_field: str = Field(..., description="Field where scopes were resolved from")
