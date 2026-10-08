"""Type definitions for always-on vault secret dynamic redaction.

[INPUT]
- Configuration options, scopes, secret sources, and text/message structures.

[OUTPUT]
- Strongly typed contracts for secret entries, redaction results, and stream states.

[POS]
- Harness core security primitive in core/security/vault_secret_redaction/types.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class RedactionScope(StrEnum):
    """Scope where the redaction is evaluated."""

    TOOL_RETURN = "tool_return"
    USER_MESSAGE = "user_message"
    STREAM_CHUNK = "stream_chunk"
    GENERIC_TEXT = "generic_text"


class SecretSourceType(StrEnum):
    """Origin of the secret registered in the redaction dictionary."""

    VAULT = "vault"
    AMBIENT_ENV = "ambient_env"
    DYNAMIC_CAPTURED = "dynamic_captured"


@dataclass(frozen=True)
class SecretEntry:
    """Represents a sensitive secret registered for active redaction."""

    name: str
    value: str
    source: SecretSourceType
    mask: str | None = None


@dataclass
class RedactionResult:
    """Summary of a completed text redaction pass."""

    clean_content: str
    redacted_count: int
    matched_secrets: list[str] = field(default_factory=list)


@dataclass
class StreamScrubChunkResult:
    """Result of pushing or flushing a chunk through the stream scrubber."""

    emitted_chunk: str
    held_back_len: int


@dataclass
class VaultSecretRedactionConfig:
    """Configuration governing redaction thresholds and formatting."""

    min_secret_length: int = 8
    mask_template: str = "{name}=<REDACTED>"
    strip_ansi: bool = True
    case_sensitive: bool = True
