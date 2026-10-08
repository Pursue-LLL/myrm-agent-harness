"""Lineage dedup and automation demotion suite for conversation recall.

[INPUT]
.models (POS: data contracts and policies)
.demotion_engine (POS: source-aware demotion and noise suppression)
.lineage_dedup (POS: generational dedup engine)
.window_hydrator (POS: asymmetric progressive window hydration)

[OUTPUT]
ConversationSourceKind, HydrationDetailLevel, SourceDemotionPolicy, LineageNode,
HydratedHit, LineageDedupAuditReport, LineageDedupResult,
SourceAwareDemotionEngine, LineageRootDedupEngine, AdaptiveWindowHydrator,
run_lineage_defense_pipeline (POS: public facade)

[POS]
Harness framework layer package entry for Item 97.
Strict typing applied: No `any` types allowed. Single file < 400 lines.
"""

from __future__ import annotations

from collections.abc import Sequence

from myrm_agent_harness.toolkits.memory.conversation_search.lineage_defense.demotion_engine import (
    SourceAwareDemotionEngine,
)
from myrm_agent_harness.toolkits.memory.conversation_search.lineage_defense.lineage_dedup import (
    LineageDedupResult,
    LineageRootDedupEngine,
)
from myrm_agent_harness.toolkits.memory.conversation_search.lineage_defense.models import (
    ConversationSourceKind,
    HydratedHit,
    HydrationDetailLevel,
    LineageDedupAuditReport,
    LineageNode,
    SourceDemotionPolicy,
)
from myrm_agent_harness.toolkits.memory.conversation_search.lineage_defense.window_hydrator import (
    AdaptiveWindowHydrator,
)

LineageDedupEngine = LineageRootDedupEngine

__all__ = [
    "AdaptiveWindowHydrator",
    "ConversationSourceKind",
    "HydratedHit",
    "HydrationDetailLevel",
    "LineageDedupAuditReport",
    "LineageDedupEngine",
    "LineageDedupResult",
    "LineageNode",
    "LineageRootDedupEngine",
    "SourceAwareDemotionEngine",
    "SourceDemotionPolicy",
    "run_lineage_defense_pipeline",
]


def run_lineage_defense_pipeline(
    candidates: Sequence[LineageNode],
    *,
    policy: SourceDemotionPolicy | None = None,
    include_internal: bool = False,
    window_size: int = 5,
    max_hits: int = 5,
) -> tuple[list[HydratedHit], LineageDedupAuditReport]:
    """Execute complete defense pipeline: demotion -> generational dedup -> progressive hydration."""
    demotion_engine = SourceAwareDemotionEngine(policy=policy)
    dedup_engine = LineageDedupEngine()
    hydrator = AdaptiveWindowHydrator(window_size=window_size)

    # 1. Source demotion & noise filter
    demoted_candidates = demotion_engine.apply_demotion(candidates, include_internal=include_internal)

    # 2. Lineage root generational dedup
    dedup_result = dedup_engine.deduplicate(demoted_candidates)

    # 3. Progressive window hydration
    hydrated_hits = hydrator.hydrate_hits(dedup_result, max_hits=max_hits)

    # 4. Audit metrics generation
    audit_report = hydrator.generate_audit_report(candidates, demoted_candidates, hydrated_hits)

    return hydrated_hits, audit_report
