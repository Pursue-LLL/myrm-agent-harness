"""Data models for Agent-Driven Memory Paging and Hard Boundary Governance Engine."""

from datetime import datetime

from pydantic import BaseModel, Field


class AccessViolationError(PermissionError):
    """Raised when an agent attempts to access memory outside its authorized hard scope."""


class PagingBudgetExceededError(RuntimeError):
    """Raised when an agent exceeds the maximum paging count or token allowance per session."""


class HardScopeContext(BaseModel):
    """Immutable physical boundary context injected at the application layer."""

    tenant_id: str = Field(description="Authorized multi-tenant identifier")
    user_id: str = Field(description="Authorized user identifier")
    project_id: str = Field(description="Active workspace or project identifier")
    session_id: str = Field(description="Current session identifier")


class MemoryPageRecord(BaseModel):
    """Structured memory entry stored within a defined physical scope boundary."""

    record_id: str = Field(description="Unique record identifier")
    scope: HardScopeContext = Field(description="Enforced physical scope boundary")
    content: str = Field(description="Textual memory payload")
    tags: list[str] = Field(default_factory=list, description="Categorization or indexing tags")
    token_count: int = Field(ge=0, description="Pre-computed token count of content")
    created_at: datetime = Field(description="Record registration timestamp")


class MemoryPageQuery(BaseModel):
    """Agent-initiated cursor pagination request for memory exploration."""

    cursor: str | None = Field(default=None, description="Opaque cursor token for next page")
    page_size: int = Field(default=5, ge=1, le=50, description="Items requested per page")
    query_text: str | None = Field(default=None, description="Optional text filter")
    filter_tags: list[str] = Field(default_factory=list, description="Optional required tags")
    purported_project_id: str | None = Field(
        default=None,
        description="Optional project ID parameter supplied by the model to test boundary enforcement",
    )


class MemoryPageResult(BaseModel):
    """Cursor-paginated response payload returned to agent tool calls."""

    records: list[MemoryPageRecord] = Field(default_factory=list, description="Returned page items")
    next_cursor: str | None = Field(default=None, description="Cursor for the subsequent page")
    has_more: bool = Field(description="Whether more records exist beyond this page")
    page_token_cost: int = Field(ge=0, description="Cumulative tokens consumed by this page")
    page_index: int = Field(ge=0, description="Current page sequence index")


class PagingBudgetPolicy(BaseModel):
    """Sliding-window quota guarding against runaway paging loops."""

    max_pages_per_session: int = Field(default=10, ge=1, description="Max allowed page queries")
    max_tokens_per_session: int = Field(default=4000, ge=100, description="Max cumulative token budget")
    used_pages: int = Field(default=0, ge=0, description="Pages retrieved in this session")
    used_tokens: int = Field(default=0, ge=0, description="Tokens delivered to this session")


class AccessViolationAudit(BaseModel):
    """Security audit entry documenting intercepted out-of-boundary access attempts."""

    violation_id: str = Field(description="Unique audit event identifier")
    session_id: str = Field(description="Offending session identifier")
    attempted_scope: str = Field(description="Scope requested or forged by agent")
    actual_scope: str = Field(description="Hard authorized scope context")
    timestamp: datetime = Field(description="Violation interception timestamp")
    details: str = Field(description="Diagnostic rationale")
