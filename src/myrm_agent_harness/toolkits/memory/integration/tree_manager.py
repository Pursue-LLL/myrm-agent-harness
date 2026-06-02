"""Integration Tree Manager — adaptive hierarchical summary tree backed by GraphStore.

[INPUT]
- GraphStore (POS: graph backend abstraction)
- IntegrationTree, IntegrationNodeKind (POS: tree data types)
- IntegrationMemory (POS: stored integration memory records)

[OUTPUT]
- IntegrationTreeManager: Build and query adaptive summary trees for integration data.

[POS]
Manages the graph-backed tree that organises integration memories into a
browsable hierarchy:  ROOT → PROVIDER → ACCOUNT → [CATEGORY…] → LEAF.

The tree uses **adaptive branching**: when a branch accumulates more leaves
than ``_BRANCH_THRESHOLD``, a CATEGORY node is inserted to keep the tree
navigable.  Summaries propagate bottom-up during the summarisation pass.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import uuid4

from myrm_agent_harness.toolkits.memory.graph.base import GraphNode, GraphStore
from myrm_agent_harness.toolkits.memory.integration.types import (
    IntegrationNodeKind,
    IntegrationTree,
)
from myrm_agent_harness.toolkits.memory.types import IntegrationMemory

logger = logging.getLogger(__name__)

_LABEL_PREFIX = "IntTree"


def _label(kind: IntegrationNodeKind) -> str:
    return f"{_LABEL_PREFIX}_{kind.value}"


class IntegrationTreeManager:
    """Build, query, and update adaptive integration summary trees.

    Each tree is identified by ``(provider, account_key)`` and stored as
    a subgraph in the shared ``GraphStore``.  The manager never owns the
    store lifecycle — it is injected from the memory system.
    """

    def __init__(self, graph_store: GraphStore) -> None:
        self._gs = graph_store
        self._trees: dict[str, IntegrationTree] = {}

    async def get_or_create_tree(
        self,
        provider: str,
        account_key: str = "",
        account_label: str = "",
    ) -> IntegrationTree:
        cache_key = f"{provider}::{account_key}"
        if cache_key in self._trees:
            return self._trees[cache_key]

        root_nodes = await self._gs.find_nodes(
            labels=[_label(IntegrationNodeKind.ROOT)],
            filters={"provider": provider, "account_key": account_key},
            limit=1,
        )

        if root_nodes:
            root = root_nodes[0]
            tree = IntegrationTree(
                id=root.id,
                provider=provider,
                account_key=account_key,
                account_label=str(root.properties.get("account_label", account_label)),
                root_summary=str(root.properties.get("summary", "")),
                leaf_count=int(root.properties.get("leaf_count", 0)),
                last_synced_at=self._parse_dt(root.properties.get("last_synced_at")),
            )
        else:
            tree_id = str(uuid4())
            await self._gs.create_node(
                labels=[_label(IntegrationNodeKind.ROOT)],
                properties={
                    "id": tree_id,
                    "provider": provider,
                    "account_key": account_key,
                    "account_label": account_label,
                    "summary": "",
                    "leaf_count": 0,
                },
            )
            tree = IntegrationTree(
                id=tree_id,
                provider=provider,
                account_key=account_key,
                account_label=account_label,
            )

        self._trees[cache_key] = tree
        return tree

    async def attach_leaf(self, tree: IntegrationTree, memory: IntegrationMemory) -> None:
        """Attach a stored IntegrationMemory as a LEAF node to the tree."""
        parent_id = await self._resolve_parent(tree, memory)

        leaf_node = await self._gs.get_or_create_node(
            labels=[_label(IntegrationNodeKind.LEAF)],
            match_keys=["memory_id"],
            properties={
                "memory_id": memory.id,
                "provider": memory.provider,
                "source_type": memory.source_type,
                "title": memory.title,
                "external_object_id": memory.external_object_id or "",
            },
        )

        await self._gs.create_relationship(
            start_id=parent_id,
            end_id=leaf_node.id,
            rel_type="HAS_LEAF",
        )

        tree.leaf_count += 1
        await self._update_root_meta(tree)

    async def get_tree_structure(self, tree_id: str) -> list[GraphNode]:
        """Return all nodes reachable from the tree root (BFS via causal chain)."""
        node_ids = await self._gs.get_causal_chain(
            tree_id, depth=10, relation_types=["HAS_PROVIDER", "HAS_ACCOUNT", "HAS_CATEGORY", "HAS_LEAF"]
        )
        nodes: list[GraphNode] = []
        for nid in node_ids:
            node = await self._gs.get_node(nid)
            if node:
                nodes.append(node)
        return nodes

    async def update_summary(self, node_id: str, summary: str) -> None:
        """Set the summary text on a tree node (provider / account / category / root)."""
        await self._gs.update_node_properties(node_id, {"summary": summary})
        for tree in self._trees.values():
            if tree.id == node_id:
                tree.root_summary = summary

    async def remove_tree(self, tree_id: str) -> int:
        """Delete an entire tree and all its graph nodes."""
        deleted = await self._gs.delete_subgraph(tree_id)
        self._trees = {k: v for k, v in self._trees.items() if v.id != tree_id}
        return deleted

    def list_trees(self, *, provider: str = "") -> list[IntegrationTree]:
        """Return cached trees, optionally filtered by provider."""
        if provider:
            return [t for t in self._trees.values() if t.provider == provider]
        return list(self._trees.values())

    # ── Internal helpers ─────────────────────────────────────────────

    async def _resolve_parent(self, tree: IntegrationTree, memory: IntegrationMemory) -> str:
        """Determine the parent node for a new leaf, creating intermediate nodes as needed."""
        provider_id = await self._ensure_provider_node(tree)

        if memory.account_key:
            parent_id = await self._ensure_account_node(tree, provider_id, memory)
        else:
            parent_id = provider_id

        if memory.source_type:
            parent_id = await self._ensure_category_node(parent_id, memory.source_type)

        return parent_id

    async def _ensure_provider_node(self, tree: IntegrationTree) -> str:
        existing = await self._gs.find_nodes(
            labels=[_label(IntegrationNodeKind.PROVIDER)],
            filters={"provider": tree.provider, "tree_id": tree.id},
            limit=1,
        )
        if existing:
            return existing[0].id

        node = await self._gs.create_node(
            labels=[_label(IntegrationNodeKind.PROVIDER)],
            properties={
                "provider": tree.provider,
                "tree_id": tree.id,
                "display_name": tree.provider,
                "summary": "",
            },
        )
        await self._gs.create_relationship(
            start_id=tree.id, end_id=node.id, rel_type="HAS_PROVIDER"
        )
        return node.id

    async def _ensure_account_node(
        self, tree: IntegrationTree, provider_node_id: str, memory: IntegrationMemory
    ) -> str:
        existing = await self._gs.find_nodes(
            labels=[_label(IntegrationNodeKind.ACCOUNT)],
            filters={"account_key": memory.account_key, "tree_id": tree.id},
            limit=1,
        )
        if existing:
            return existing[0].id

        node = await self._gs.create_node(
            labels=[_label(IntegrationNodeKind.ACCOUNT)],
            properties={
                "account_key": memory.account_key,
                "account_label": memory.account_label,
                "tree_id": tree.id,
                "summary": "",
            },
        )
        await self._gs.create_relationship(
            start_id=provider_node_id, end_id=node.id, rel_type="HAS_ACCOUNT"
        )
        return node.id

    async def _ensure_category_node(self, parent_id: str, category: str) -> str:
        existing = await self._gs.find_nodes(
            labels=[_label(IntegrationNodeKind.CATEGORY)],
            filters={"category": category, "parent_id": parent_id},
            limit=1,
        )
        if existing:
            return existing[0].id

        node = await self._gs.create_node(
            labels=[_label(IntegrationNodeKind.CATEGORY)],
            properties={
                "category": category,
                "parent_id": parent_id,
                "summary": "",
            },
        )
        await self._gs.create_relationship(
            start_id=parent_id, end_id=node.id, rel_type="HAS_CATEGORY"
        )
        return node.id

    async def _update_root_meta(self, tree: IntegrationTree) -> None:
        now_str = datetime.now(UTC).isoformat()
        await self._gs.update_node_properties(
            tree.id,
            {"leaf_count": tree.leaf_count, "last_synced_at": now_str},
        )
        tree.last_synced_at = datetime.now(UTC)

    @staticmethod
    def _parse_dt(val: str | int | float | bool | None) -> datetime | None:
        if val is None or not isinstance(val, str) or not val:
            return None
        try:
            dt = datetime.fromisoformat(val)
            return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
        except ValueError:
            return None
