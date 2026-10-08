# [INPUT]: None
# [OUTPUT]: HydrationDecision, HydrationMode, JITToolHydrationConfig, ToolSchemaDescriptor, VirtualCatalogIndex
# [POS]: agent/context_management/jit_tool_hydration/hydration_types.py

"""Domain models and contracts for low-context friendly JIT tool hydration and virtual catalog.

[INPUT]
- None (Self-contained domain models and contracts).

[OUTPUT]
- HydrationMode: Operating mode for tool schema exposure (FULL_CATALOG, JIT_HYDRATION, ALWAYS_LEAN).
- ToolSchemaDescriptor: Normalized tool schema definition with token weight metadata.
- VirtualCatalogIndex: Compact virtual catalog projection representation and cost.
- HydrationDecision: Resolved turn-level decision containing active full schemas and virtual index.
- JITToolHydrationConfig: Configuration governing context threshold, limits, and core tool anchors.

[POS]
Domain contract layer for lean context tool hydration and virtual catalog indexing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Sequence


class HydrationMode(str, Enum):
    """Execution mode determining whether schemas are fully expanded or JIT hydrated."""

    FULL_CATALOG = "full_catalog"    # High context (>128k): expose all full schemas for parallel calls
    JIT_HYDRATION = "jit_hydration"  # Lean context (<=64k): compact catalog index + JIT hydration
    ALWAYS_LEAN = "always_lean"      # Ultra-constrained: minimal core tools + strictly lazy loading


@dataclass(frozen=True)
class ToolSchemaDescriptor:
    """Normalized definition of a tool including name, summary, and schema payload."""

    name: str
    short_summary: str
    schema_payload: Mapping[str, str | int | float | bool | Sequence[str] | Mapping[str, str]]
    estimated_tokens: int
    is_core_pinned: bool = False
    intent_keywords: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class VirtualCatalogIndex:
    """Compact string-serialized index representing tools without massive JSON schemas."""

    catalog_text: str
    tool_names: tuple[str, ...]
    total_tools_count: int
    estimated_catalog_tokens: int


@dataclass(frozen=True)
class HydrationDecision:
    """Authoritative decision detailing active hydrated tools and token savings."""

    mode: HydrationMode
    active_tool_names: tuple[str, ...]
    active_schemas: tuple[Mapping[str, str | int | float | bool | Sequence[str] | Mapping[str, str]], ...]
    virtual_catalog_header: str
    total_registered_tools: int
    hydrated_tools_count: int
    estimated_tokens_used: int
    estimated_tokens_saved: int
    savings_percentage: float


@dataclass(frozen=True)
class JITToolHydrationConfig:
    """Config controlling thresholds for lean mode admission, hydration limits, and core tools."""

    lean_context_threshold: int = 65536
    default_mode: HydrationMode = HydrationMode.JIT_HYDRATION
    max_hydrated_tools_per_turn: int = 6
    core_tools_whitelist: tuple[str, ...] = ("bash", "file_read")
    average_token_char_ratio: float = 4.0
