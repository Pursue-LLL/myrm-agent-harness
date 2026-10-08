"""Virtual tool catalog indexer producing ultra-compact prompt-cache friendly tool summaries.

[INPUT]
- ToolSchemaDescriptor, VirtualCatalogIndex: Domain contract definitions.

[OUTPUT]
- VirtualToolCatalogIndexer: Pure compiler compressing massive tool schemas into low-token indices.

[POS]
Index compilation and compression layer for low-context tool catalog representation.
"""

from __future__ import annotations

import math
from typing import Mapping, Sequence

from .hydration_types import ToolSchemaDescriptor, VirtualCatalogIndex


class VirtualToolCatalogIndexer:
    """Compiles registered tool definitions into ultra-compact, low-token virtual indices."""

    def __init__(self, char_to_token_ratio: float = 4.0) -> None:
        self._char_to_token_ratio = max(1.0, char_to_token_ratio)

    def compile_catalog(
        self,
        tools: Sequence[ToolSchemaDescriptor],
        unhydrated_only: bool = True,
        active_hydrated_names: Sequence[str] | None = None,
    ) -> VirtualCatalogIndex:
        """Serializes tool descriptors into an ultra-lean tag that costs <5 tokens per tool."""
        active_set = set(active_hydrated_names or ())

        selected_tools = [
            t for t in tools
            if not (unhydrated_only and t.name in active_set)
        ]

        if not selected_tools:
            return VirtualCatalogIndex(
                catalog_text="",
                tool_names=(),
                total_tools_count=len(tools),
                estimated_catalog_tokens=0,
            )

        # Build compact format: name(short summary)
        compact_entries: list[str] = []
        tool_names_list: list[str] = []

        for item in selected_tools:
            tool_names_list.append(item.name)
            summary = item.short_summary.strip()
            if summary:
                compact_entries.append(f"{item.name}({summary})")
            else:
                compact_entries.append(item.name)

        catalog_body = "; ".join(compact_entries)
        header_text = (
            f"<virtual_tool_catalog count=\"{len(selected_tools)}\">\n"
            f"Available unhydrated tools: {catalog_body}\n"
            f"Note: Declare tool name or intent to automatically hydrate full parameter schema.\n"
            f"</virtual_tool_catalog>"
        )

        estimated_tokens = max(1, math.ceil(len(header_text) / self._char_to_token_ratio))

        return VirtualCatalogIndex(
            catalog_text=header_text,
            tool_names=tuple(tool_names_list),
            total_tools_count=len(tools),
            estimated_catalog_tokens=estimated_tokens,
        )

    def calculate_full_schemas_token_cost(
        self,
        tools: Sequence[ToolSchemaDescriptor],
    ) -> int:
        """Sums estimated token expenditures for exposing all tool schemas in full JSON."""
        return sum(item.estimated_tokens for item in tools)
