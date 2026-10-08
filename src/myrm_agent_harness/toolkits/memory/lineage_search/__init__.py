"""LineageDedupRecallBlindnessDefenseAndAutomationDemotionSuite.

Provides lineage root deduplication across multi-generation compacted sessions,
source-aware demotion of high-frequency cron automation (Hermes PR #19434),
and adaptive token-conserving window hydration.

[INPUT]
- toolkits.memory.lineage_search.lineage_deduplicator::LineageDeduplicator (POS: Collapses multi-generation
  compacted or branched session continuations.)
- toolkits.memory.lineage_search.lineage_search_engine::LineageSearchEngine (POS: Full-stack session retrieval
  engine with FTS5 lexical matching,.)
- toolkits.memory.lineage_search.models::ConversationMessage, HydratedSessionHit, LineageSearchOptions,
  LineageSearchStats, RawSearchHit, SessionMeta, SessionSourceKind (POS: Types and models for lineage search.)
- toolkits.memory.lineage_search.source_demoter::SourceDemoterAndFilter (POS: Implements source-aware
  filtering and demotion policies inspired by Hermes Agent PR #19434.)
- toolkits.memory.lineage_search.window_hydrator::AdaptiveWindowHydrator (POS: Hydrates surviving search hits
  with two-tier adaptive detail:.)

[OUTPUT]
- Re-exports: AdaptiveWindowHydrator, ConversationMessage, HydratedSessionHit, LineageDeduplicator,
  LineageSearchEngine, LineageSearchOptions, LineageSearchStats, RawSearchHit, SessionMeta, SessionSourceKind,
  SourceDemoterAndFilter

[POS]
LineageDedupRecallBlindnessDefenseAndAutomationDemotionSuite.
"""

from myrm_agent_harness.toolkits.memory.lineage_search.lineage_deduplicator import LineageDeduplicator
from myrm_agent_harness.toolkits.memory.lineage_search.lineage_search_engine import LineageSearchEngine
from myrm_agent_harness.toolkits.memory.lineage_search.models import (
    ConversationMessage,
    HydratedSessionHit,
    LineageSearchOptions,
    LineageSearchStats,
    RawSearchHit,
    SessionMeta,
    SessionSourceKind,
)
from myrm_agent_harness.toolkits.memory.lineage_search.source_demoter import SourceDemoterAndFilter
from myrm_agent_harness.toolkits.memory.lineage_search.window_hydrator import AdaptiveWindowHydrator

__all__ = [
    "AdaptiveWindowHydrator",
    "ConversationMessage",
    "HydratedSessionHit",
    "LineageDeduplicator",
    "LineageSearchEngine",
    "LineageSearchOptions",
    "LineageSearchStats",
    "RawSearchHit",
    "SessionMeta",
    "SessionSourceKind",
    "SourceDemoterAndFilter",
]
