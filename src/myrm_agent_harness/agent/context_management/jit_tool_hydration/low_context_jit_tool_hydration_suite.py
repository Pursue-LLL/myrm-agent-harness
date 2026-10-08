"""Unified facade suite for low-context friendly JIT tool hydration and virtual catalog.

[INPUT]
- HydrationDecision, HydrationMode, JITToolHydrationConfig, ToolSchemaDescriptor: Domain models.
- VirtualToolCatalogIndexer: Catalog compression and indexer component.
- JITSchemaHydrationEngine: Intent-driven JIT tool schema expansion engine.
- PostExecutionToolDehydrator: Schema garbage collection and post-turn dehydration tracker.

[OUTPUT]
- LowContextFriendlyJITToolHydrationAndVirtualCatalogSuite: Cohesive facade coordinating virtual catalog
  indexing, intent-driven JIT hydration, and post-turn schema reclamation.

[POS]
Top-level entry point for low-context tool schema governance in context management.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from .hydration_types import (
    HydrationDecision,
    HydrationMode,
    JITToolHydrationConfig,
    ToolSchemaDescriptor,
)
from .jit_schema_hydration_engine import JITSchemaHydrationEngine
from .post_execution_tool_dehydrator import PostExecutionToolDehydrator
from .virtual_tool_catalog_indexer import VirtualToolCatalogIndexer


class LowContextFriendlyJITToolHydrationAndVirtualCatalogSuite:
    """Industrial facade coordinating virtual tool catalogs, JIT hydration, and turn-level GC."""

    def __init__(
        self,
        config: JITToolHydrationConfig | None = None,
        indexer: VirtualToolCatalogIndexer | None = None,
        hydration_engine: JITSchemaHydrationEngine | None = None,
        dehydrator: PostExecutionToolDehydrator | None = None,
    ) -> None:
        self._config = config or JITToolHydrationConfig()
        self._indexer = indexer or VirtualToolCatalogIndexer(self._config.average_token_char_ratio)
        self._engine = hydration_engine or JITSchemaHydrationEngine(self._config, self._indexer)
        self._dehydrator = dehydrator or PostExecutionToolDehydrator(self._config)

    @property
    def config(self) -> JITToolHydrationConfig:
        """Returns the active configuration."""
        return self._config

    @property
    def registered_tools_count(self) -> int:
        """Returns the total number of registered tool schemas."""
        return self._engine.registered_tools_count

    def register_tool(self, descriptor: ToolSchemaDescriptor) -> None:
        """Registers a tool schema into the virtual catalog."""
        self._engine.register_tool(descriptor)

    def register_tools(self, descriptors: Sequence[ToolSchemaDescriptor]) -> None:
        """Registers a batch of tool schemas into the virtual catalog."""
        self._engine.register_tools(descriptors)

    def resolve_turn_tools(
        self,
        session_id: str,
        recent_prompts: Sequence[str],
        model_context_window: int | None = None,
        explicit_requested_tools: Sequence[str] | None = None,
        mode_override: HydrationMode | None = None,
    ) -> HydrationDecision:
        """Computes optimal schema exposure, mounting matching tools and compressing the remainder."""
        active_in_session = self._dehydrator.get_active_hydrated_tools(session_id)

        decision = self._engine.resolve_hydration(
            recent_prompts=recent_prompts,
            active_session_hydrated_names=active_in_session,
            explicit_requested_tools=explicit_requested_tools,
            mode_override=mode_override,
            model_context_window=model_context_window,
        )

        # Update session tracker with newly hydrated tools
        if decision.active_tool_names:
            self._dehydrator.mark_tools_hydrated(session_id, decision.active_tool_names)

        # Record savings telemetry
        if decision.estimated_tokens_saved > 0:
            self._dehydrator.record_turn_savings(session_id, decision.estimated_tokens_saved)

        return decision

    def dehydrate_turn(
        self,
        session_id: str,
        preserve_core: bool = True,
    ) -> tuple[str, ...]:
        """Evicts non-core hydrated tools back to virtual catalog after turn execution concludes."""
        return self._dehydrator.dehydrate_after_turn(
            session_id=session_id,
            preserve_core=preserve_core,
        )

    def get_active_hydrated_tools(self, session_id: str) -> tuple[str, ...]:
        """Inspects currently mounted tools for the given session."""
        return self._dehydrator.get_active_hydrated_tools(session_id)

    def get_cumulative_savings(self, session_id: str) -> int:
        """Queries cumulative tokens saved for this session across all executed turns."""
        return self._dehydrator.get_cumulative_savings(session_id)

    def reset_session(self, session_id: str) -> None:
        """Cleans up session tracking upon conversation close or reset."""
        self._dehydrator.clear_session(session_id)
