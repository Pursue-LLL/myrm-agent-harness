"""Type definitions for Memory Defense Ingestion Firewall and PII Sanitization Suite."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class DefenseAction(StrEnum):
    """Tri-state ingestion enforcement decisions."""

    ALLOW = "ALLOW"
    REDACT = "REDACT"
    BLOCK = "BLOCK"


class SensitiveCategory(StrEnum):
    """Categories of sensitive secrets and PII patterns."""

    API_KEY = "API_KEY"
    CLOUD_CREDENTIAL = "CLOUD_CREDENTIAL"
    PRIVATE_KEY = "PRIVATE_KEY"
    DATABASE_URL = "DATABASE_URL"
    TOKEN_JWT = "TOKEN_JWT"
    PII_ID = "PII_ID"
    PII_FINANCIAL = "PII_FINANCIAL"
    PII_CONTACT = "PII_CONTACT"


@dataclass(slots=True, frozen=True)
class PatternSpec:
    """Specification of a regex sensitive detection pattern."""

    pattern_id: str
    name: str
    category: SensitiveCategory
    regex_pattern: str
    replacement_tag: str
    description: str


@dataclass(slots=True, frozen=True)
class DetectionMatch:
    """Detailed record of a single sensitive token found in text."""

    pattern_id: str
    pattern_name: str
    category: SensitiveCategory
    start: int
    end: int
    matched_preview: str
    replacement_tag: str


@dataclass(slots=True)
class DefensePolicy:
    """Configuration determining how sensitive findings are treated."""

    default_action: DefenseAction = DefenseAction.REDACT
    blocked_categories: set[SensitiveCategory] = field(default_factory=set)
    redacted_categories: set[SensitiveCategory] = field(default_factory=set)


@dataclass(slots=True, frozen=True)
class MemoryDefenseResult:
    """Evaluation outcome of inspecting ingested memory text."""

    action_taken: DefenseAction
    is_admitted: bool
    sanitized_text: str
    original_length: int
    sanitized_length: int
    matches: list[DetectionMatch] = field(default_factory=list)
    audit_id: str = ""
    timestamp: float = 0.0
