"""Low-context friendly JIT tool hydration and virtual catalog package.

[INPUT]
- None (Package root exports).

[OUTPUT]
- HydrationDecision: Resolved turn-level tool hydration decision.
- HydrationMode: Execution modes (FULL_CATALOG, JIT_HYDRATION, ALWAYS_LEAN).
- JITSchemaHydrationEngine: Intent-driven JIT tool schema expansion engine.
- JITToolHydrationConfig: Configuration governing context threshold, limits, and core tools.
- LowContextFriendlyJITToolHydrationAndVirtualCatalogSuite: Unified facade coordinating virtual catalogs,
  intent hydration, and post-execution garbage collection.
- PostExecutionToolDehydrator: Schema garbage collection and post-turn dehydration tracker.
- ToolSchemaDescriptor: Normalized tool schema definition with token metadata.
- VirtualCatalogIndex: Compact virtual catalog projection representation and cost.
- VirtualToolCatalogIndexer: Pure compiler compressing massive tool schemas into low-token indices.

[POS]
Package entry point for lean context tool hydration and virtual catalog in context management.
"""

from __future__ import annotations

from .hydration_types import (
    HydrationDecision,
    HydrationMode,
    JITToolHydrationConfig,
    ToolSchemaDescriptor,
    VirtualCatalogIndex,
)
from .jit_schema_hydration_engine import JITSchemaHydrationEngine
from .low_context_jit_tool_hydration_suite import (
    LowContextFriendlyJITToolHydrationAndVirtualCatalogSuite,
)
from .post_execution_tool_dehydrator import PostExecutionToolDehydrator
from .virtual_tool_catalog_indexer import VirtualToolCatalogIndexer

__all__ = [
    "HydrationDecision",
    "HydrationMode",
    "JITSchemaHydrationEngine",
    "JITToolHydrationConfig",
    "LowContextFriendlyJITToolHydrationAndVirtualCatalogSuite",
    "PostExecutionToolDehydrator",
    "ToolSchemaDescriptor",
    "VirtualCatalogIndex",
    "VirtualToolCatalogIndexer",
]
