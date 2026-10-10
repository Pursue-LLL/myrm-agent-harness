"""Memory consolidation engine clustering and reshaping fragmented rules (Item 158).

[INPUT]
- MemoryItemProfile items list, consolidation thresholds, and execution payloads.

[OUTPUT]
- ConsolidationProposal candidates and synthesized consolidated MemoryItemProfile records.

[POS]
- Consolidation engine in myrm_agent_harness/toolkits/memory/staleness_consolidation/.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime, timezone

from .models import ConsolidationProposal, MemoryItemProfile


class MemoryConsolidationEngine:
    """Discovers fragmentation clusters and reshapes multiple incremental memories into unified rules."""

    def __init__(self, min_cluster_size: int = 2) -> None:
        self.min_cluster_size = max(2, min_cluster_size)

    def propose_consolidations(
        self,
        items: list[MemoryItemProfile],
    ) -> list[ConsolidationProposal]:
        """Group memories by category and propose consolidation if cluster threshold met."""
        clusters: dict[str, list[MemoryItemProfile]] = defaultdict(list)

        # Only cluster active or stale items; skip already consolidated or archived ones
        for item in items:
            if item.status in ("active", "stale"):
                clusters[item.category].append(item)

        proposals: list[ConsolidationProposal] = []
        for category, grouped_items in clusters.items():
            if len(grouped_items) >= self.min_cluster_size:
                source_ids = [it.memory_id for it in grouped_items]
                cluster_key = f"{category}_{len(source_ids)}"
                proposal_id = f"prop_{uuid.uuid5(uuid.NAMESPACE_DNS, cluster_key).hex[:10]}"

                bullet_points = "\n".join(f"- {it.content.strip()}" for it in grouped_items)
                proposed_content = (
                    f"【统一生效准则 · {category.upper()}】\n"
                    f"整合自 {len(grouped_items)} 条历史碎片规则：\n"
                    f"{bullet_points}"
                )

                rationale = (
                    f"检测到类别 '{category}' 下存在 {len(grouped_items)} 条碎片化规则，"
                    f"合并重塑可消除重复注意力消耗并降低 Token 占用。"
                )

                proposals.append(
                    ConsolidationProposal(
                        proposal_id=proposal_id,
                        source_memory_ids=source_ids,
                        category=category,
                        proposed_content=proposed_content,
                        rationale=rationale,
                    )
                )

        return proposals

    def apply_consolidation(
        self,
        proposal: ConsolidationProposal,
        items_map: dict[str, MemoryItemProfile],
        now_iso: str | None = None,
    ) -> MemoryItemProfile:
        """Execute consolidation: produce unified memory and mark source memories as consolidated."""
        now_str = now_iso or datetime.now(timezone.utc).isoformat()
        new_memory_id = f"mem_cons_{proposal.proposal_id}"

        # Collect merged path references and assertions
        merged_paths: list[str] = []
        merged_assertions: list[str] = []

        for src_id in proposal.source_memory_ids:
            if src_id in items_map:
                src_item = items_map[src_id]
                src_item.status = "consolidated"
                src_item.subsumed_by_id = new_memory_id

                for p in src_item.referenced_paths:
                    if p not in merged_paths:
                        merged_paths.append(p)
                for a in src_item.referenced_assertions:
                    if a not in merged_assertions:
                        merged_assertions.append(a)

        new_item = MemoryItemProfile(
            memory_id=new_memory_id,
            content=proposal.proposed_content,
            category=proposal.category,
            created_at=now_str,
            last_recalled_at=now_str,
            recalled_count=1,
            staleness_score=0.0,
            status="active",
            referenced_paths=merged_paths,
            referenced_assertions=merged_assertions,
        )

        items_map[new_memory_id] = new_item
        return new_item
