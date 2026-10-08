"""Source-aware demotion engine for conversation recall.

[INPUT]
.models::ConversationSourceKind, LineageNode, SourceDemotionPolicy (POS: core lineage domain models)
typing::Sequence, typing::List (POS: strict typing contracts)

[OUTPUT]
SourceAwareDemotionEngine: engine applying source categorization, worker suppression, and cron score penalty.

[POS]
Harness framework layer engine for Item 97.
Implements Hermes PR #19434 wisdom: demote, do not unconditionally drop cron sessions,
ensuring interactive sessions surface first while cron remains reachable when only match.
Strict typing applied: No `any` types allowed. Single file < 400 lines.
"""

from __future__ import annotations

from collections.abc import Sequence

from myrm_agent_harness.toolkits.memory.conversation_search.lineage_defense.models import (
    ConversationSourceKind,
    LineageNode,
    SourceDemotionPolicy,
)


class SourceAwareDemotionEngine:
    """Engine that applies source-based penalty and background noise filtering to search candidates."""

    def __init__(self, policy: SourceDemotionPolicy | None = None) -> None:
        self.policy = policy or SourceDemotionPolicy()

    def apply_demotion(
        self,
        nodes: Sequence[LineageNode],
        *,
        include_internal: bool = False,
    ) -> list[LineageNode]:
        """Apply source-aware demotion and filtering on candidate session nodes.

        Rules:
        1. INTERNAL_WORKER is filtered out unless include_internal is True or policy specifies otherwise.
        2. CRON_SCHEDULED scores are multiplied by cron_weight_multiplier (e.g. 0.45).
        3. INTERACTIVE scores are amplified by interactive_priority_boost (e.g. 1.0).
        4. When both interactive and cron match, interactive surfaces on top.
        5. When ONLY cron matches, cron remains retained and reachable (no false empty result).
        """
        filtered_candidates: list[LineageNode] = []
        for node in nodes:
            if node.source_kind == ConversationSourceKind.INTERNAL_WORKER:
                if self.policy.hide_internal_workers and not include_internal:
                    continue
                node_copy = node.model_copy(
                    update={"final_score": round(node.raw_score * 0.2, 4)}
                )
                filtered_candidates.append(node_copy)
            elif node.source_kind == ConversationSourceKind.CRON_SCHEDULED:
                demoted_score = round(node.raw_score * self.policy.cron_weight_multiplier, 4)
                node_copy = node.model_copy(update={"final_score": demoted_score})
                filtered_candidates.append(node_copy)
            else:
                boosted_score = round(node.raw_score * self.policy.interactive_priority_boost, 4)
                node_copy = node.model_copy(update={"final_score": boosted_score})
                filtered_candidates.append(node_copy)

        # Sort by final_score descending; if scores are equal, prioritize INTERACTIVE
        def sort_key(item: LineageNode) -> tuple[float, int, float]:
            priority = 2 if item.source_kind == ConversationSourceKind.INTERACTIVE else (
                1 if item.source_kind == ConversationSourceKind.CRON_SCHEDULED else 0
            )
            # Generation higher is newer, secondary criterion
            return (item.final_score, priority, float(item.generation))

        filtered_candidates.sort(key=sort_key, reverse=True)
        return filtered_candidates
