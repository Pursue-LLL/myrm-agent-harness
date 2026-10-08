"""Lineage root generational deduplication engine for conversation recall.

[INPUT]
.models::LineageNode (POS: core session node schema)
typing::Sequence, typing::List, typing::Dict (POS: typing contracts)

[OUTPUT]
LineageDedupResult: DTO holding primary retained nodes and collapsed lineage mapping.
LineageRootDedupEngine: dedup engine collapsing older compaction/fork generations under their lineage root.

[POS]
Harness framework layer engine for Item 97.
Resolves multi-generation session pollution where 5 slices of the same long-running task
compete for BM25 result slots, eliminating redundancy while preserving ancestry traceability.
Strict typing applied: No `any` types allowed. Single file < 400 lines.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field

from myrm_agent_harness.toolkits.memory.conversation_search.lineage_defense.models import LineageNode


class LineageDedupResult(BaseModel):
    """Result envelope of lineage generational deduplication."""

    model_config = ConfigDict(extra="forbid")

    primary_nodes: list[LineageNode] = Field(description="Primary representative nodes retained per lineage root")
    collapsed_count_map: dict[str, int] = Field(
        default_factory=dict,
        description="Mapping from primary session_id to number of collapsed ancestor/sibling generations",
    )
    collapsed_ids_map: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Mapping from primary session_id to list of collapsed session IDs",
    )


class LineageRootDedupEngine:
    """Engine that aggregates candidates by lineage_root_id and retains the freshest generation."""

    def deduplicate(self, nodes: Sequence[LineageNode]) -> LineageDedupResult:
        """Deduplicate nodes belonging to the same lineage root.

        Selection strategy for the primary representative:
        1. Higher generation index (freshest compacted/evolved state).
        2. If generation ties, higher final_score.
        3. If still ties, latest updated_at or first seen.
        """
        if not nodes:
            return LineageDedupResult(primary_nodes=[], collapsed_count_map={}, collapsed_ids_map={})

        lineage_groups: dict[str, list[LineageNode]] = {}
        for node in nodes:
            root_id = node.lineage_root_id or node.session_id
            if root_id not in lineage_groups:
                lineage_groups[root_id] = []
            lineage_groups[root_id].append(node)

        primary_nodes: list[LineageNode] = []
        collapsed_count_map: dict[str, int] = {}
        collapsed_ids_map: dict[str, list[str]] = {}

        for _root_id, group in lineage_groups.items():
            # Sort group to find the best representative
            sorted_group = sorted(
                group,
                key=lambda item: (
                    item.generation,
                    item.final_score,
                    item.updated_at.timestamp() if item.updated_at else 0.0,
                ),
                reverse=True,
            )
            primary = sorted_group[0]
            other_nodes = sorted_group[1:]

            primary_nodes.append(primary)
            collapsed_count_map[primary.session_id] = len(other_nodes)
            collapsed_ids_map[primary.session_id] = [n.session_id for n in other_nodes]

        # Preserve descending score order among primary nodes
        primary_nodes.sort(key=lambda n: n.final_score, reverse=True)

        return LineageDedupResult(
            primary_nodes=primary_nodes,
            collapsed_count_map=collapsed_count_map,
            collapsed_ids_map=collapsed_ids_map,
        )
