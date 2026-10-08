"""Just-in-time tool schema hydration engine matching intents and mounting schemas on demand.

[INPUT]
- HydrationDecision, HydrationMode, JITToolHydrationConfig, ToolSchemaDescriptor: Domain types.
- VirtualToolCatalogIndexer: Catalog indexing and compression component.

[OUTPUT]
- JITSchemaHydrationEngine: Engine matching conversational intent to hydrate tools dynamically.

[POS]
Intent-driven JIT hydration and schema expansion layer for low-context tool management.
"""

from __future__ import annotations

import re
from typing import Mapping, Sequence

from .hydration_types import (
    HydrationDecision,
    HydrationMode,
    JITToolHydrationConfig,
    ToolSchemaDescriptor,
)
from .virtual_tool_catalog_indexer import VirtualToolCatalogIndexer


class JITSchemaHydrationEngine:
    """Detects invocation intent from conversation turns and mounts tool schemas JIT."""

    def __init__(
        self,
        config: JITToolHydrationConfig | None = None,
        indexer: VirtualToolCatalogIndexer | None = None,
    ) -> None:
        self._config = config or JITToolHydrationConfig()
        self._indexer = indexer or VirtualToolCatalogIndexer(self._config.average_token_char_ratio)
        self._registry: dict[str, ToolSchemaDescriptor] = {}

    def register_tool(self, descriptor: ToolSchemaDescriptor) -> None:
        """Registers a tool schema into the catalog."""
        self._registry[descriptor.name] = descriptor

    def register_tools(self, descriptors: Sequence[ToolSchemaDescriptor]) -> None:
        """Batch registers multiple tool schemas."""
        for desc in descriptors:
            self.register_tool(desc)

    def get_tool(self, tool_name: str) -> ToolSchemaDescriptor | None:
        """Retrieves a specific tool descriptor by name."""
        return self._registry.get(tool_name)

    @property
    def registered_tools_count(self) -> int:
        """Returns the total number of registered tools."""
        return len(self._registry)

    def resolve_hydration(
        self,
        recent_prompts: Sequence[str],
        active_session_hydrated_names: Sequence[str] | None = None,
        explicit_requested_tools: Sequence[str] | None = None,
        mode_override: HydrationMode | None = None,
        model_context_window: int | None = None,
    ) -> HydrationDecision:
        """Computes authoritative hydration decision based on context window and turn intent."""
        all_tools = list(self._registry.values())
        total_registered = len(all_tools)

        # 1. Determine execution mode
        effective_mode = self._resolve_mode(mode_override, model_context_window)

        # In FULL_CATALOG mode, expose all registered schemas without virtualization
        if effective_mode == HydrationMode.FULL_CATALOG:
            full_schemas = tuple(t.schema_payload for t in all_tools)
            names = tuple(t.name for t in all_tools)
            used_tokens = sum(t.estimated_tokens for t in all_tools)
            return HydrationDecision(
                mode=effective_mode,
                active_tool_names=names,
                active_schemas=full_schemas,
                virtual_catalog_header="",
                total_registered_tools=total_registered,
                hydrated_tools_count=total_registered,
                estimated_tokens_used=used_tokens,
                estimated_tokens_saved=0,
                savings_percentage=0.0,
            )

        # 2. Gather candidates: Core tools + Explicitly requested + Session active + Intent matched
        hydrated_set: set[str] = set()

        # Core whitelist tools are always hydrated
        for tool_name in self._config.core_tools_whitelist:
            if tool_name in self._registry:
                hydrated_set.add(tool_name)

        # Explicitly requested tools
        if explicit_requested_tools:
            for tool_name in explicit_requested_tools:
                if tool_name in self._registry:
                    hydrated_set.add(tool_name)

        # Previously active in this session turn cycle
        if active_session_hydrated_names:
            for tool_name in active_session_hydrated_names:
                if tool_name in self._registry:
                    hydrated_set.add(tool_name)

        # Scan text for intent matches if room remains under max_hydrated_tools_per_turn
        combined_text = " ".join(recent_prompts).lower()
        if len(hydrated_set) < self._config.max_hydrated_tools_per_turn:
            for tool_name, desc in self._registry.items():
                if tool_name in hydrated_set:
                    continue
                if self._matches_intent(tool_name, desc, combined_text):
                    hydrated_set.add(tool_name)
                    if len(hydrated_set) >= self._config.max_hydrated_tools_per_turn:
                        break

        # 3. Assemble active schemas and virtual catalog index
        active_tools = [self._registry[name] for name in hydrated_set if name in self._registry]
        active_names = tuple(t.name for t in active_tools)
        active_schemas = tuple(t.schema_payload for t in active_tools)

        # Compile compact catalog for remaining unhydrated tools
        catalog_index = self._indexer.compile_catalog(
            tools=all_tools,
            unhydrated_only=True,
            active_hydrated_names=active_names,
        )

        # 4. Calculate savings
        total_full_tokens = sum(t.estimated_tokens for t in all_tools)
        used_tokens = sum(t.estimated_tokens for t in active_tools) + catalog_index.estimated_catalog_tokens
        saved_tokens = max(0, total_full_tokens - used_tokens)
        savings_percentage = round((saved_tokens / total_full_tokens * 100.0), 2) if total_full_tokens > 0 else 0.0

        return HydrationDecision(
            mode=effective_mode,
            active_tool_names=active_names,
            active_schemas=active_schemas,
            virtual_catalog_header=catalog_index.catalog_text,
            total_registered_tools=total_registered,
            hydrated_tools_count=len(active_tools),
            estimated_tokens_used=used_tokens,
            estimated_tokens_saved=saved_tokens,
            savings_percentage=savings_percentage,
        )

    def _resolve_mode(
        self,
        mode_override: HydrationMode | None,
        context_window: int | None,
    ) -> HydrationMode:
        if mode_override is not None:
            return mode_override
        if context_window is not None:
            if context_window <= self._config.lean_context_threshold:
                return HydrationMode.JIT_HYDRATION
            return HydrationMode.FULL_CATALOG
        return self._config.default_mode

    def _matches_intent(
        self,
        tool_name: str,
        desc: ToolSchemaDescriptor,
        text: str,
    ) -> bool:
        # Match exact tool name word boundary
        if re.search(rf"\b{re.escape(tool_name.lower())}\b", text):
            return True
        # Match configured intent keywords
        for keyword in desc.intent_keywords:
            if keyword.lower() in text:
                return True
        return False
