"""Dynamic Tool Schema Pruner with Progressive Disclosure.

References ratel-ai context engineering (~80% token saving by pruning 5000+ token tool sets down to 200-500 tokens).
Indexes tool specifications via InProcessBM25Retriever and dynamically activates Core + Top-K tools per turn.
Strict 0 Any, type-hinted, thread-safe.

[INPUT]
- runtime.context.in_process_bm25_retriever::InProcessBM25Retriever (POS: In-process sub-millisecond BM25
  lexical retriever for AI agent context engineering.)
- runtime.context.in_process_bm25_types::ProgressiveDisclosureConfig, PrunedToolSet, ToolSchemaEntry (POS:
  Type definitions for In-Process BM25 Lexical Retriever and Dynamic Tool Schema Pruner.)

[OUTPUT]
- DynamicToolSchemaPruner: Orchestrates dynamic tool schema pruning and progressive disclosure via
  in-process BM25.

[POS]
Dynamic Tool Schema Pruner with Progressive Disclosure.
"""

from __future__ import annotations

import threading
from collections.abc import Sequence

from .in_process_bm25_retriever import InProcessBM25Retriever
from .in_process_bm25_types import (
    ProgressiveDisclosureConfig,
    PrunedToolSet,
    ToolSchemaEntry,
)


class DynamicToolSchemaPruner:
    """Orchestrates dynamic tool schema pruning and progressive disclosure via in-process BM25."""

    def __init__(self, config: ProgressiveDisclosureConfig | None = None) -> None:
        self._config = config or ProgressiveDisclosureConfig()
        self._lock = threading.RLock()
        self._tools: dict[str, ToolSchemaEntry] = {}
        self._retriever = InProcessBM25Retriever(k1=self._config.k1, b=self._config.b)

    def register_tool(self, tool: ToolSchemaEntry) -> None:
        """Register a tool and index its lexical metadata."""
        with self._lock:
            self._tools[tool.name] = tool
            content = f"{tool.name} {tool.description} {' '.join(tool.keywords)}"
            meta: dict[str, str | int | float | bool] = {
                "category": tool.category,
                "is_core": tool.is_core,
            }
            self._retriever.index_document(doc_id=tool.name, content=content, metadata=meta)

    def register_tools_batch(self, tools: Sequence[ToolSchemaEntry]) -> int:
        """Batch register and index multiple tools."""
        with self._lock:
            for tool in tools:
                self.register_tool(tool)
            return len(tools)

    def prune_for_query(
        self,
        query: str,
        active_context_snippets: Sequence[str] = (),
    ) -> PrunedToolSet:
        """Dynamically prune tool schemas for the given query and conversation context.

        Guarantees all Core tools are preserved, and selects Top-K relevant specialized tools.
        """
        with self._lock:
            all_tools = list(self._tools.values())
            if not all_tools:
                return PrunedToolSet(
                    active_tools=(),
                    pruned_tool_names=(),
                    original_token_estimate=0,
                    pruned_token_estimate=0,
                    token_saving_ratio=0.0,
                    expansion_directive="",
                )

            # 1. Identify core tools (always retained)
            core_tools: list[ToolSchemaEntry] = []
            core_names = set(self._config.core_tool_names)
            for tool in all_tools:
                if tool.is_core or tool.name in core_names:
                    core_tools.append(tool)

            core_names_set = {t.name for t in core_tools}

            # 2. Retrieve Top-K dynamic tools via in-process BM25
            search_query = query.strip()
            if active_context_snippets:
                search_query += " " + " ".join(active_context_snippets)

            matched_hits = self._retriever.search(
                query=search_query,
                top_k=len(all_tools),  # query all to filter out core tools
                min_score=self._config.min_score_threshold,
            )

            dynamic_selected: list[ToolSchemaEntry] = []
            for hit in matched_hits:
                if hit.doc_id not in core_names_set and hit.doc_id in self._tools:
                    dynamic_selected.append(self._tools[hit.doc_id])
                    if len(dynamic_selected) >= self._config.top_k:
                        break

            # 3. Assemble active tools and compute pruning statistics
            active_tools = tuple(core_tools + dynamic_selected)
            active_names_set = {t.name for t in active_tools}
            pruned_names = tuple(t.name for t in all_tools if t.name not in active_names_set)

            orig_tokens = sum(t.estimated_tokens for t in all_tools)
            pruned_tokens = sum(t.estimated_tokens for t in active_tools)
            saving_ratio = (
                round((orig_tokens - pruned_tokens) / orig_tokens, 4)
                if orig_tokens > 0
                else 0.0
            )

            # 4. Generate progressive disclosure expansion directive
            expansion_directive = ""
            if pruned_names and self._config.allow_dynamic_expansion:
                expansion_directive = (
                    f"<tool_progressive_disclosure active_count='{len(active_tools)}' "
                    f"pruned_count='{len(pruned_names)}' token_savings='{saving_ratio:.1%}'>\n"
                    f"Active tools: {', '.join(t.name for t in active_tools)}.\n"
                    f"Additional dormant tools: {', '.join(pruned_names)}.\n"
                    f"If you need any dormant tools to complete your task, output a tool request or ask the user.\n"
                    f"</tool_progressive_disclosure>"
                )

            return PrunedToolSet(
                active_tools=active_tools,
                pruned_tool_names=pruned_names,
                original_token_estimate=orig_tokens,
                pruned_token_estimate=pruned_tokens,
                token_saving_ratio=saving_ratio,
                expansion_directive=expansion_directive,
            )

    def expand_tool_set(
        self,
        current_pruned: PrunedToolSet,
        requested_names: Sequence[str],
    ) -> PrunedToolSet:
        """Dynamically expand the active tool set by waking up pruned tools on demand."""
        with self._lock:
            all_tools = list(self._tools.values())
            active_map = {t.name: t for t in current_pruned.active_tools}
            expanded_names = set(requested_names)

            for name in expanded_names:
                if name in self._tools and name not in active_map:
                    active_map[name] = self._tools[name]

            new_active_tools = tuple(active_map.values())
            new_active_names = set(active_map.keys())
            new_pruned_names = tuple(
                t.name for t in all_tools if t.name not in new_active_names
            )

            orig_tokens = sum(t.estimated_tokens for t in all_tools)
            pruned_tokens = sum(t.estimated_tokens for t in new_active_tools)
            saving_ratio = (
                round((orig_tokens - pruned_tokens) / orig_tokens, 4)
                if orig_tokens > 0
                else 0.0
            )

            expansion_directive = ""
            if new_pruned_names and self._config.allow_dynamic_expansion:
                expansion_directive = (
                    f"<tool_progressive_disclosure active_count='{len(new_active_tools)}' "
                    f"pruned_count='{len(new_pruned_names)}' token_savings='{saving_ratio:.1%}'>\n"
                    f"Active tools: {', '.join(t.name for t in new_active_tools)}.\n"
                    f"Additional dormant tools: {', '.join(new_pruned_names)}.\n"
                    f"</tool_progressive_disclosure>"
                )

            return PrunedToolSet(
                active_tools=new_active_tools,
                pruned_tool_names=new_pruned_names,
                original_token_estimate=orig_tokens,
                pruned_token_estimate=pruned_tokens,
                token_saving_ratio=saving_ratio,
                expansion_directive=expansion_directive,
            )

    @property
    def registered_count(self) -> int:
        """Total number of registered tools."""
        with self._lock:
            return len(self._tools)
