"""[POS]: src/myrm_agent_harness/toolkits/memory/directory_dominance/retriever.py
[INPUT]: Hierarchical node structures, directory dominance heuristics, and query parameters.
[OUTPUT]: HierarchicalDirectoryDominanceRetriever implementation with convergence bounds and sibling bundling.
"""

from collections import defaultdict

from .models import (
    DirectoryDominanceConfig,
    DominanceDecisionKind,
    HierarchicalNode,
    HierarchicalRetrievalHit,
    HierarchicalRetrievalResult,
    HierarchicalRetrievalStats,
    HierarchyNodeType,
    SiblingContextItem,
)


class HierarchicalDirectoryDominanceRetriever:
    """Hierarchical retriever leveraging directory dominance ratios and sibling context bundling."""

    def __init__(self, config: DirectoryDominanceConfig | None = None) -> None:
        self.config = config or DirectoryDominanceConfig()

    def evaluate_dominance(
        self,
        dir_node: HierarchicalNode,
        children_nodes: list[HierarchicalNode],
    ) -> DominanceDecisionKind:
        """Evaluate whether a directory node dominates its children based on dominance_ratio."""
        if not children_nodes:
            return DominanceDecisionKind.BALANCED

        valid_children = [c for c in children_nodes if c.score >= self.config.min_score_threshold]
        if not valid_children:
            return (
                DominanceDecisionKind.DIRECTORY_DOMINANT
                if dir_node.score >= self.config.min_score_threshold
                else DominanceDecisionKind.BALANCED
            )

        max_child_score = max(c.score for c in valid_children)

        # Directory dominance condition: dir_score >= max_child_score * dominance_ratio
        dominance_threshold = max_child_score * self.config.dominance_ratio
        if dir_node.score >= dominance_threshold and dir_node.score > 0.0:
            return DominanceDecisionKind.DIRECTORY_DOMINANT

        if max_child_score > dir_node.score:
            return DominanceDecisionKind.LEAF_SPECIFIC

        return DominanceDecisionKind.BALANCED

    def bundle_siblings(
        self,
        target_node: HierarchicalNode,
        all_nodes_map: dict[str, HierarchicalNode],
        parent_children_map: dict[str, list[str]],
    ) -> list[SiblingContextItem]:
        """Bundle top sibling summaries to prevent isolated, out-of-context reasoning."""
        if not target_node.parent_uri or self.config.max_siblings_per_hit <= 0:
            return []

        sibling_uris = parent_children_map.get(target_node.parent_uri, [])
        siblings = [
            all_nodes_map[uri]
            for uri in sibling_uris
            if uri != target_node.uri and uri in all_nodes_map
        ]

        # Prioritize siblings by relevance score, then by name
        sorted_siblings = sorted(
            siblings,
            key=lambda item: (item.score, item.name),
            reverse=True,
        )

        selected_siblings = sorted_siblings[: self.config.max_siblings_per_hit]
        return [
            SiblingContextItem(
                uri=sib.uri,
                name=sib.name,
                abstract=sib.abstract or sib.content[:160],
                relation="sibling",
            )
            for sib in selected_siblings
        ]

    def retrieve(
        self,
        query: str,
        nodes: list[HierarchicalNode],
        limit: int = 5,
    ) -> HierarchicalRetrievalResult:
        """Execute hierarchical directory dominance retrieval with convergence control."""
        if not nodes:
            return HierarchicalRetrievalResult(
                query=query,
                hits=[],
                stats=HierarchicalRetrievalStats(
                    convergence_rounds=1,
                    nodes_evaluated=0,
                    dominant_directories_count=0,
                    leaf_hits_count=0,
                    total_siblings_bundled=0,
                ),
            )

        # 1. Build lookup maps
        all_nodes_map: dict[str, HierarchicalNode] = {node.uri: node for node in nodes}
        parent_children_map: dict[str, list[str]] = defaultdict(list)
        for node in nodes:
            if node.parent_uri:
                parent_children_map[node.parent_uri].append(node.uri)

        # 2. Discover root entry points (nodes without parent or parent outside set)
        root_candidates = [
            node for node in nodes if not node.parent_uri or node.parent_uri not in all_nodes_map
        ]
        if not root_candidates:
            root_candidates = nodes

        # 3. Iterative hierarchical exploration with convergence control
        current_active = root_candidates
        evaluated_uris: set[str] = set()
        chosen_hits: list[HierarchicalRetrievalHit] = []
        dominant_dirs_count = 0
        leaf_hits_count = 0
        total_siblings = 0
        round_idx = 0

        while round_idx < self.config.max_convergence_rounds and current_active:
            round_idx += 1
            next_active: list[HierarchicalNode] = []
            previous_hits_count = len(chosen_hits)

            for active_node in current_active:
                if active_node.uri in evaluated_uris:
                    continue
                evaluated_uris.add(active_node.uri)

                child_uris = parent_children_map.get(active_node.uri, [])
                children = [all_nodes_map[u] for u in child_uris if u in all_nodes_map]

                if active_node.node_type == HierarchyNodeType.DIRECTORY and children:
                    decision = self.evaluate_dominance(active_node, children)
                    if decision == DominanceDecisionKind.DIRECTORY_DOMINANT:
                        dominant_dirs_count += 1
                        chosen_hits.append(
                            HierarchicalRetrievalHit(
                                uri=active_node.uri,
                                node_type=active_node.node_type,
                                score=active_node.score,
                                decision=decision,
                                abstract=active_node.abstract,
                                content=active_node.content,
                                parent_uri=active_node.parent_uri,
                                parent_summary=None,
                                sibling_contexts=[],
                            )
                        )
                        # Dominant directory prunes children subtree exploration
                        continue

                    # Fan-out bounded children exploration
                    sorted_children = sorted(children, key=lambda c: c.score, reverse=True)
                    fan_out = sorted_children[: self.config.max_parallel_child_searches]
                    next_active.extend(fan_out)
                else:
                    # Leaf, file, or childless node
                    if active_node.score >= self.config.min_score_threshold:
                        siblings = self.bundle_siblings(
                            active_node,
                            all_nodes_map,
                            parent_children_map,
                        )
                        parent_node = (
                            all_nodes_map.get(active_node.parent_uri)
                            if active_node.parent_uri
                            else None
                        )
                        parent_summary = (
                            (parent_node.abstract or parent_node.content[:200])
                            if (parent_node and self.config.include_parent_context)
                            else None
                        )

                        leaf_hits_count += 1
                        total_siblings += len(siblings)
                        chosen_hits.append(
                            HierarchicalRetrievalHit(
                                uri=active_node.uri,
                                node_type=active_node.node_type,
                                score=active_node.score,
                                decision=DominanceDecisionKind.LEAF_SPECIFIC,
                                abstract=active_node.abstract,
                                content=active_node.content,
                                parent_uri=active_node.parent_uri,
                                parent_summary=parent_summary,
                                sibling_contexts=siblings,
                            )
                        )

            # Check convergence stability
            if len(chosen_hits) == previous_hits_count and not next_active:
                break
            current_active = next_active

        # 4. Global deduplication and score ranking
        dedup_hits: dict[str, HierarchicalRetrievalHit] = {}
        for hit in chosen_hits:
            existing = dedup_hits.get(hit.uri)
            if existing is None or hit.score > existing.score:
                dedup_hits[hit.uri] = hit

        ranked_hits = sorted(dedup_hits.values(), key=lambda h: h.score, reverse=True)[:limit]

        return HierarchicalRetrievalResult(
            query=query,
            hits=ranked_hits,
            stats=HierarchicalRetrievalStats(
                convergence_rounds=round_idx,
                nodes_evaluated=len(evaluated_uris),
                dominant_directories_count=dominant_dirs_count,
                leaf_hits_count=leaf_hits_count,
                total_siblings_bundled=total_siblings,
            ),
        )
