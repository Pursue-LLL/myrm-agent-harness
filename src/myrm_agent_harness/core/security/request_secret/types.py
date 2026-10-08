"""
[POS] src/myrm_agent_harness/core/security/request_secret/types.py
[INPUT] enum, typing, pydantic
[OUTPUT] SecretRequestStatus, MaskedCredentialRef, SecretRequestIntent,
         SecretCardSession, SecretInputSubmission, SanitizedSecretResult
Domain types for Request-Secret Masked Credential Card Suite.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class SecretRequestStatus(StrEnum):
    """Lifecycle status of a secret request card session."""

    PENDING = "pending"
    FULFILLED = "fulfilled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class MaskedCredentialRef(BaseModel):
    """Safe, transcript-friendly reference to an existing stored credential."""

    credential_id: str = Field(..., description="Unique opaque credential identifier")
    target_system: str = Field(..., description="Target system or service, e.g. github, aws, stripe")
    mask_preview: str = Field(..., description="Masked display fingerprint (e.g. ghp_****1234)")
    created_at: float = Field(..., description="Creation epoch timestamp")


class SecretRequestIntent(BaseModel):
    """Agent's structured specification requesting a task-scoped secret."""

    target_system: str = Field(..., min_length=1, description="Target destination system (e.g. github, openai)")
    purpose_description: str = Field(..., min_length=1, description="Human-understandable justification")
    scope: str = Field(default="default", description="Requested access permission scope")
    ttl_seconds: int = Field(default=3600, ge=60, le=86400, description="Authorized credential time-to-live in seconds")


class SecretCardSession(BaseModel):
    """Interactive card session presented to user for providing or selecting credentials."""

    card_id: str = Field(..., description="Unique secret card session ID")
    agent_id: str = Field(..., description="Requesting agent identifier")
    task_id: str = Field(..., description="Task or run identifier")
    intent: SecretRequestIntent = Field(..., description="Requested intent specifications")
    status: SecretRequestStatus = Field(default=SecretRequestStatus.PENDING, description="Current card status")
    masked_ref: MaskedCredentialRef | None = Field(default=None, description="Resolved masked credential reference if fulfilled")
    rejection_reason: str | None = Field(default=None, description="Reason if user rejected request")
    created_at: float = Field(..., description="Session creation timestamp")
    expires_at: float = Field(..., description="Session expiration timestamp")


class SecretInputSubmission(BaseModel):
    """User submission providing either a newly inputted secret or selecting an existing masked credential."""

    raw_secret: str | None = Field(default=None, description="Raw plaintext secret (will be encrypted immediately)")
    selected_credential_id: str | None = Field(
        default=None,
        description="ID of an existing saved credential selected for backfill",
    )
    extra_metadata: dict[str, str] = Field(
        default_factory=dict,
        description="Optional clean key-value metadata",
    )


class SanitizedSecretResult(BaseModel):
    """Sanitized resolution payload safe for emitting to agent loop and transcript."""

    card_id: str = Field(..., description="Resolved card session identifier")
    target_system: str = Field(..., description="Target system identifier")
    mask_preview: str = Field(..., description="Masked fingerprint of secret")
    is_backfill: bool = Field(default=False, description="Whether credential was fulfilled via existing saved backfill")
    stored_safely: bool = Field(default=True, description="Whether secret was successfully stored in secure vault")
    transcript_safe_summary: str = Field(..., description="Transcript-safe narrative without raw secret exposure")
