"""Types and models for canonical tool.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- ToolDefinitionInput: Raw input representation of an agent tool definition before canonicalization.
- CanonicalToolDefinition: Normalized tool specification with RFC 8785 canonical JSON schema.
- FrozenToolPrefixBundle: Byte-frozen tool prefix payload guaranteed byte-for-byte identical across runs.
- PrefixDriftDiagnosis: Diagnostic report on prefix hash drift between two consecutive tool sets.

[POS]
Types and models for canonical tool.
"""

# ============================================================================
# Deterministic Tool Schema Canonicalizer & Prefix Hasher Contracts (Item 167)
# Strong typing contracts for RFC 8785 JSON canonicalization, deterministic tool
# alphabetical sorting, byte-level prefix freezing, and cache drift diagnosis.
# ============================================================================

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(frozen=True, slots=True)
class ToolDefinitionInput:
    """Raw input representation of an agent tool definition before canonicalization."""

    name: str
    description: str
    parameters: Mapping[str, object]
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CanonicalToolDefinition:
    """Normalized tool specification with RFC 8785 canonical JSON schema."""

    name: str
    description: str
    parameters_canonical_json: str
    tool_sha256: str
    byte_size: int


@dataclass(frozen=True, slots=True)
class FrozenToolPrefixBundle:
    """Byte-frozen tool prefix payload guaranteed byte-for-byte identical across runs."""

    prefix_hash: str
    canonical_payload_bytes: bytes
    tool_count: int
    sorted_tool_names: tuple[str, ...]
    tools: tuple[CanonicalToolDefinition, ...]
    frozen_at_iso: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass(frozen=True, slots=True)
class PrefixDriftDiagnosis:
    """Diagnostic report on prefix hash drift between two consecutive tool sets."""

    has_drift: bool
    previous_hash: str
    current_hash: str
    added_tools: tuple[str, ...]
    removed_tools: tuple[str, ...]
    modified_tools: tuple[str, ...]
    detail_reason: str
