"""
[POS] src/myrm_agent_harness/core/security/execution_approval_sanitizer/types.py
[INPUT] dataclasses, enum, typing
[OUTPUT] SecretType, RedactionFinding, SanitizationResult, ApprovalPayloadRequest, SanitizerMetrics
Domain types for Execution Approval Secret Redaction & In-Band Presentation Sanitizer Suite.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class SecretType(StrEnum):
    """Categorization of sensitive credentials detected in approval texts."""

    OPENAI_API_KEY = "OPENAI_API_KEY"
    ANTHROPIC_API_KEY = "ANTHROPIC_API_KEY"
    GITHUB_TOKEN = "GITHUB_TOKEN"
    AWS_CREDENTIAL = "AWS_CREDENTIAL"
    SLACK_TOKEN = "SLACK_TOKEN"
    BEARER_TOKEN = "BEARER_TOKEN"
    DATABASE_PASSWORD = "DATABASE_PASSWORD"
    GENERIC_HIGH_ENTROPY_SECRET = "GENERIC_HIGH_ENTROPY_SECRET"


@dataclass(frozen=True)
class RedactionFinding:
    """Individual sensitive credential occurrence located and sanitized."""

    secret_type: SecretType
    start_index: int
    end_index: int
    matched_preview: str
    placeholder: str


@dataclass(frozen=True)
class SanitizationResult:
    """Outcome of cleansing command text, including redacted string and diagnostic audit badge."""

    sanitized_text: str
    redactions_count: int
    detected_secret_types: tuple[SecretType, ...]
    findings: tuple[RedactionFinding, ...]
    badge_summary: str


@dataclass(frozen=True)
class ApprovalPayloadRequest:
    """Command text or approval prompt payload submitted for presentation sanitization."""

    request_id: str
    session_id: str
    raw_command_or_text: str
    channel_target: str = "webui"
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass
class SanitizerMetrics:
    """Cumulative operational metrics for execution approval secret redaction."""

    payloads_evaluated_total: int = 0
    clean_payloads_total: int = 0
    redacted_payloads_total: int = 0
    total_secrets_redacted_count: int = 0
