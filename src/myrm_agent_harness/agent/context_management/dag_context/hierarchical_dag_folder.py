"""Hierarchical DAG folder orchestrating multi-tier progressive summarization and lineage.

[INPUT]
- TurnRecord, HierarchicalDagNode, DagNodeLevel, DagContextBudgetConfig: Domain contracts.

[OUTPUT]
- HierarchicalDagFolder: Fold turns into Level-1 page summary nodes and Level-2 root skeleton nodes.

[POS]
Graph folding layer in DAG context subsystem preserving long-range lineage without context blowout.
"""

from __future__ import annotations

import time
from typing import Sequence

from .dag_types import (
    DagContextBudgetConfig,
    DagNodeLevel,
    HierarchicalDagNode,
    TurnRecord,
)


class HierarchicalDagFolder:
    """Manages two-tier hierarchical folding of turns into DAG nodes with lineage pointers."""

    def __init__(self, config: DagContextBudgetConfig | None = None) -> None:
        self._config = config or DagContextBudgetConfig()
        self._raw_turns: list[TurnRecord] = []
        self._page_nodes: list[HierarchicalDagNode] = []
        self._root_node: HierarchicalDagNode | None = None
        self._page_counter: int = 1

    def append_turn(self, turn: TurnRecord) -> None:
        """Append a new turn and trigger progressive folding if thresholds are reached."""
        self._raw_turns.append(turn)
        self._evaluate_folding()

    def _evaluate_folding(self) -> None:
        """Check whether old turns should be folded into Level-1 and Level-2 DAG nodes."""
        keep_recent = self._config.recent_turns_unconditionally_kept
        threshold = self._config.page_fold_turn_threshold

        # Calculate already folded turns offset
        folded_turn_count = sum(
            self._count_turns_in_node(p) for p in self._page_nodes
        )
        unfolded_turns = self._raw_turns[folded_turn_count:]

        # Need at least threshold + keep_recent turns to fold a new page
        if len(unfolded_turns) >= threshold + keep_recent:
            chunk_to_fold = unfolded_turns[:threshold]
            new_page = self._synthesize_page_node(chunk_to_fold)
            self._page_nodes.append(new_page)

            # Check if Level-1 nodes exceed threshold for Level-2 root synthesis
            if len(self._page_nodes) >= self._config.max_page_nodes_before_root_fold:
                self._synthesize_root_skeleton()

    def _count_turns_in_node(self, node: HierarchicalDagNode) -> int:
        """Extract number of turns represented by this node range."""
        try:
            start_idx = next(i for i, t in enumerate(self._raw_turns) if t.turn_id == node.turn_range[0])
            end_idx = next(i for i, t in enumerate(self._raw_turns) if t.turn_id == node.turn_range[1])
            return end_idx - start_idx + 1
        except StopIteration:
            return 0

    def _synthesize_page_node(self, turns: Sequence[TurnRecord]) -> HierarchicalDagNode:
        """Synthesize a Level-1 page summary node from a contiguous chunk of raw turns."""
        page_id = f"page-{self._page_counter}"
        self._page_counter += 1

        start_turn = turns[0].turn_id
        end_turn = turns[-1].turn_id

        summary_points: list[str] = []
        for t in turns:
            preview = t.content.strip().replace("\n", " ")
            if len(preview) > 120:
                preview = preview[:120] + "..."
            summary_points.append(f"Turn {t.turn_id} ({t.role}): {preview}")

        summary_text = "\n".join(summary_points)
        est_tokens = len(summary_text.split())

        return HierarchicalDagNode(
            node_id=page_id,
            level=DagNodeLevel.PAGE_SUMMARY,
            title=f"Page #{page_id} [Turns {start_turn}..{end_turn}]",
            content=summary_text,
            turn_range=(start_turn, end_turn),
            child_ids=tuple(t.turn_id for t in turns),
            token_count=est_tokens,
            created_at=time.time(),
        )

    def _synthesize_root_skeleton(self) -> None:
        """Synthesize a higher-order Level-2 root DAG skeleton consolidating all Level-1 pages."""
        now = time.time()
        start_turn = self._page_nodes[0].turn_range[0]
        end_turn = self._page_nodes[-1].turn_range[1]

        condensed_bullets: list[str] = [
            f"- [{p.node_id}]: {p.title} ({p.token_count} tokens)"
            for p in self._page_nodes
        ]
        content = (
            "# [Higher-Order Context Root Skeleton]\n"
            + "\n".join(condensed_bullets)
        )

        self._root_node = HierarchicalDagNode(
            node_id="dag-root",
            level=DagNodeLevel.ROOT_SKELETON,
            title=f"Root Context Skeleton [Turns {start_turn}..{end_turn}]",
            content=content,
            turn_range=(start_turn, end_turn),
            child_ids=tuple(p.node_id for p in self._page_nodes),
            token_count=len(content.split()),
            created_at=now,
        )

    def get_page_nodes(self) -> Sequence[HierarchicalDagNode]:
        """Return all Level-1 page nodes."""
        return tuple(self._page_nodes)

    def get_root_node(self) -> HierarchicalDagNode | None:
        """Return the synthesized Level-2 root skeleton node, if any."""
        return self._root_node

    def get_active_unfolded_turns(self) -> Sequence[TurnRecord]:
        """Return current recent turns that remain unfolded in active working context."""
        folded_turn_count = sum(
            self._count_turns_in_node(p) for p in self._page_nodes
        )
        return tuple(self._raw_turns[folded_turn_count:])

    def get_raw_turns(self) -> Sequence[TurnRecord]:
        """Return all immutable turns recorded so far."""
        return tuple(self._raw_turns)
