"""Integration Summariser — LLM-powered multi-level tree summarisation.

[INPUT]
- IntegrationTreeManager (POS: tree node traversal)
- GraphStore (POS: node property read/write)
- Callable[str, str] (POS: injected LLM text generation function)

[OUTPUT]
- IntegrationSummariser: Bottom-up summary propagation for integration trees.

[POS]
After a sync run, the summariser walks the tree bottom-up and generates
compact summaries for each intermediate and root node.  These summaries
are stored as graph node properties and can be surfaced to the user or
injected into the agent context as high-level orientation.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine

from myrm_agent_harness.toolkits.memory.graph.base import GraphNode, GraphStore
from myrm_agent_harness.toolkits.memory.integration.tree_manager import IntegrationTreeManager
from myrm_agent_harness.toolkits.memory.integration.types import IntegrationNodeKind

logger = logging.getLogger(__name__)

SummariseFn = Callable[[str], Coroutine[None, None, str]]

_LEAF_BATCH_SIZE = 50
_SUMMARY_MAX_CHARS = 500

_CHILD_SUMMARY_PROMPT = (
    "Merge the following sub-summaries into one cohesive summary "
    "(max {max_chars} chars):\n\n{children}"
)

_LEAF_PROMPT = (
    "Summarise the following {count} data entries from {provider} "
    "(type: {source_type}):\n\n{entries}"
)


class IntegrationSummariser:
    """Bottom-up LLM summarisation for integration trees.

    ``summarise_fn`` is an async callable ``(prompt: str) -> str`` that
    wraps the LLM call.  The business layer injects the concrete
    implementation so the framework stays LLM-agnostic.
    """

    def __init__(
        self,
        graph_store: GraphStore,
        tree_manager: IntegrationTreeManager,
        summarise_fn: SummariseFn,
        *,
        max_summary_chars: int = _SUMMARY_MAX_CHARS,
    ) -> None:
        self._gs = graph_store
        self._tree = tree_manager
        self._summarise = summarise_fn
        self._max_chars = max_summary_chars

    async def summarise_tree(self, tree_id: str) -> str:
        """Run bottom-up summarisation for an entire tree.  Returns root summary."""
        root = await self._gs.get_node(tree_id)
        if root is None:
            logger.warning("Tree root %s not found, skipping summarisation", tree_id)
            return ""

        summary = await self._summarise_node(root, visited=set())
        await self._tree.update_summary(tree_id, summary)
        return summary

    async def _summarise_node(self, node: GraphNode, *, visited: set[str]) -> str:
        """Recursively summarise a tree node with cycle detection."""
        if node.id in visited:
            return ""
        visited.add(node.id)

        children = await self._get_children(node.id)

        if not children:
            return str(node.properties.get("summary", node.properties.get("title", "")))

        child_summaries: list[str] = []
        for child in children:
            label_str = " ".join(child.labels)
            if "LEAF" in label_str or IntegrationNodeKind.LEAF.value in label_str.lower():
                child_summaries.append(self._leaf_to_text(child))
            else:
                sub_summary = await self._summarise_node(child, visited=visited)
                if sub_summary:
                    child_summaries.append(sub_summary)

        if not child_summaries:
            return ""

        provider = str(node.properties.get("provider", "unknown"))
        source_type = str(node.properties.get("category", node.properties.get("source_type", "")))

        leaf_labels = [c for c in children if any("LEAF" in lb or "leaf" in lb for lb in c.labels)]
        non_leaf_labels = [c for c in children if c not in leaf_labels]

        if leaf_labels and not non_leaf_labels:
            prompt = _LEAF_PROMPT.format(
                count=len(child_summaries),
                provider=provider,
                source_type=source_type or "mixed",
                entries="\n---\n".join(child_summaries[:_LEAF_BATCH_SIZE]),
            )
        else:
            prompt = _CHILD_SUMMARY_PROMPT.format(
                max_chars=self._max_chars,
                children="\n---\n".join(child_summaries),
            )

        try:
            summary = await self._summarise(prompt)
        except Exception as exc:
            logger.error("LLM summarisation failed for node %s: %s", node.id, exc)
            summary = "; ".join(child_summaries[:3])[:self._max_chars]

        await self._gs.update_node_properties(node.id, {"summary": summary})
        return summary

    async def _get_children(self, node_id: str) -> list[GraphNode]:
        child_ids = await self._gs.get_causal_chain(
            node_id, depth=1,
            relation_types=["HAS_PROVIDER", "HAS_ACCOUNT", "HAS_CATEGORY", "HAS_LEAF"],
        )
        nodes: list[GraphNode] = []
        for cid in child_ids:
            if cid == node_id:
                continue
            node = await self._gs.get_node(cid)
            if node:
                nodes.append(node)
        return nodes

    @staticmethod
    def _leaf_to_text(node: GraphNode) -> str:
        title = str(node.properties.get("title", ""))
        src_type = str(node.properties.get("source_type", ""))
        parts: list[str] = []
        if src_type:
            parts.append(f"[{src_type}]")
        if title:
            parts.append(title)
        return " ".join(parts) if parts else node.id
