"""Package facade for canonical tool.

[INPUT]
- agent.context_management.canonical_tool.canonical_tool_serializer::DeterministicToolSchemaCanonicalizer,
  rfc8785_canonicalize_json (POS: Canonicalizer ensuring byte-level deterministic stability for tool
  prefixes.)
- agent.context_management.canonical_tool.canonical_tool_types::CanonicalToolDefinition,
  FrozenToolPrefixBundle, PrefixDriftDiagnosis, ToolDefinitionInput (POS: Types and models for canonical
  tool.)

[OUTPUT]
- Re-exports: CanonicalToolDefinition, DeterministicToolSchemaCanonicalizer, FrozenToolPrefixBundle,
  PrefixDriftDiagnosis, ToolDefinitionInput, rfc8785_canonicalize_json

[POS]
Package facade for canonical tool.
"""

# ============================================================================
# Deterministic Tool Schema Canonicalizer & Prefix Hasher Package (Item 167)
# ============================================================================

from .canonical_tool_serializer import (
    DeterministicToolSchemaCanonicalizer,
    rfc8785_canonicalize_json,
)
from .canonical_tool_types import (
    CanonicalToolDefinition,
    FrozenToolPrefixBundle,
    PrefixDriftDiagnosis,
    ToolDefinitionInput,
)

__all__ = [
    "CanonicalToolDefinition",
    "DeterministicToolSchemaCanonicalizer",
    "FrozenToolPrefixBundle",
    "PrefixDriftDiagnosis",
    "ToolDefinitionInput",
    "rfc8785_canonicalize_json",
]
