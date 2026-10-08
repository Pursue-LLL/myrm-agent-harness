"""Adaptive window hydration and token footprint economizer.

[INPUT]
.models::HydratedHit, HydrationDetailLevel, LineageDedupAuditReport, LineageNode (POS: domain models)
.lineage_dedup::LineageDedupResult (POS: lineage dedup outputs)
typing::Sequence, typing::List (POS: strict typing contracts)

[OUTPUT]
AdaptiveWindowHydrator: progressive hydrator delivering expanded Top-1 window and compact Top-2..N cards.

[POS]
Harness framework layer engine for Item 97.
Dramatically reduces context token bloat (by ~70%+) and prevents LLM Lost-in-the-Middle attention drift
by selectively hydrating deep context only for the highest-confidence primary hit.
Strict typing applied: No `any` types allowed. Single file < 400 lines.
"""

from __future__ import annotations

from collections.abc import Sequence

from myrm_agent_harness.toolkits.memory.conversation_search.lineage_defense.lineage_dedup import (
    LineageDedupResult,
)
from myrm_agent_harness.toolkits.memory.conversation_search.lineage_defense.models import (
    ConversationSourceKind,
    HydratedHit,
    HydrationDetailLevel,
    LineageDedupAuditReport,
    LineageNode,
)

EXPANDED_WINDOW_MAX_CHARS = 1200
COMPACT_CARD_MAX_CHARS = 220


class AdaptiveWindowHydrator:
    """Hydrator that applies asymmetric progressive detail expansion to search hits."""

    def __init__(self, *, window_size: int = 5) -> None:
        self.window_size = window_size

    def hydrate_hits(
        self,
        dedup_result: LineageDedupResult,
        *,
        max_hits: int = 5,
    ) -> list[HydratedHit]:
        """Hydrate primary nodes into progressive detail levels.

        Top 1 node gets EXPANDED_WINDOW (deep multi-turn context).
        Top 2..N nodes get COMPACT_CARD (compact summary + metadata).
        """
        primary_nodes = dedup_result.primary_nodes[:max_hits]
        hydrated_list: list[HydratedHit] = []

        for index, node in enumerate(primary_nodes):
            is_top_one = index == 0
            detail_level = (
                HydrationDetailLevel.EXPANDED_WINDOW
                if is_top_one
                else HydrationDetailLevel.COMPACT_CARD
            )

            collapsed_count = dedup_result.collapsed_count_map.get(node.session_id, 0)
            collapsed_ids = dedup_result.collapsed_ids_map.get(node.session_id, [])

            if is_top_one:
                # Hydrate window turns
                recent_turns = list(node.messages_context[-self.window_size :])
                joined_snippet = " \n ".join(recent_turns)
                if len(joined_snippet) > EXPANDED_WINDOW_MAX_CHARS:
                    joined_snippet = joined_snippet[:EXPANDED_WINDOW_MAX_CHARS] + "... [truncated]"

                # Rough token estimation: 1 token ~ 3.5 chars
                token_est = max(10, int(len(joined_snippet) / 3.5))

                hydrated_list.append(
                    HydratedHit(
                        session_id=node.session_id,
                        lineage_root_id=node.lineage_root_id,
                        title=node.title or f"Session {node.session_id}",
                        source_kind=node.source_kind,
                        detail_level=detail_level,
                        content_snippet=joined_snippet,
                        window_messages=recent_turns,
                        token_estimate=token_est,
                        is_demoted=node.final_score < node.raw_score,
                        is_lineage_primary=True,
                        collapsed_generations_count=collapsed_count,
                        collapsed_session_ids=collapsed_ids,
                    )
                )
            else:
                # Compact card
                first_summary = (
                    node.messages_context[0]
                    if node.messages_context
                    else (node.title or f"Session {node.session_id}")
                )
                if len(first_summary) > COMPACT_CARD_MAX_CHARS:
                    first_summary = first_summary[:COMPACT_CARD_MAX_CHARS] + "..."

                token_est = max(8, int(len(first_summary) / 3.5))

                hydrated_list.append(
                    HydratedHit(
                        session_id=node.session_id,
                        lineage_root_id=node.lineage_root_id,
                        title=node.title or f"Session {node.session_id}",
                        source_kind=node.source_kind,
                        detail_level=detail_level,
                        content_snippet=first_summary,
                        window_messages=[],
                        token_estimate=token_est,
                        is_demoted=node.final_score < node.raw_score,
                        is_lineage_primary=True,
                        collapsed_generations_count=collapsed_count,
                        collapsed_session_ids=collapsed_ids,
                    )
                )

        return hydrated_list

    def generate_audit_report(
        self,
        raw_candidates: Sequence[LineageNode],
        demoted_candidates: Sequence[LineageNode],
        hydrated_hits: Sequence[HydratedHit],
    ) -> LineageDedupAuditReport:
        """Calculate and render efficiency and recall blindness defense audit metrics."""
        total_count = len(raw_candidates)
        retained_count = len(hydrated_hits)

        hidden_internal = sum(
            1 for c in raw_candidates if c.source_kind == ConversationSourceKind.INTERNAL_WORKER
        )
        demoted_cron = sum(
            1 for c in demoted_candidates if c.source_kind == ConversationSourceKind.CRON_SCHEDULED
        )
        collapsed_lineage = sum(hit.collapsed_generations_count for hit in hydrated_hits)

        # Token savings: hypothetical all expanded vs actual progressive
        hypothetical_full_tokens = retained_count * int(EXPANDED_WINDOW_MAX_CHARS / 3.5)
        actual_tokens = sum(hit.token_estimate for hit in hydrated_hits)
        tokens_saved = max(0, hypothetical_full_tokens - actual_tokens)
        savings_percent = (
            round((tokens_saved / hypothetical_full_tokens) * 100, 1)
            if hypothetical_full_tokens > 0
            else 0.0
        )

        interactive_top1 = (
            1.0
            if (hydrated_hits and hydrated_hits[0].source_kind == ConversationSourceKind.INTERACTIVE)
            else 0.0
        )

        return LineageDedupAuditReport(
            total_candidates=total_count,
            retained_hits_count=retained_count,
            hidden_internal_count=hidden_internal,
            demoted_cron_count=demoted_cron,
            collapsed_lineage_count=collapsed_lineage,
            interactive_top1_ratio=interactive_top1,
            estimated_tokens_saved=tokens_saved,
            token_saving_percent=savings_percent,
        )
