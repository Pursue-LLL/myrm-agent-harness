"""Unit test suite for LineageDedupRecallBlindnessDefenseAndAutomationDemotionSuite.

[INPUT]
myrm_agent_harness.toolkits.memory.conversation_search.lineage_defense (POS: lineage defense package)
datetime::datetime, datetime::timezone (POS: temporal fixtures)

[OUTPUT]
TestLineageDefenseSuite: 6 comprehensive unit tests verifying source demotion,
generational dedup, adaptive window hydration, and audit report generation.

[POS]
Harness framework test for Item 97.
Strict typing applied: No `any` types allowed. Single file < 400 lines.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from myrm_agent_harness.toolkits.memory.conversation_search.lineage_defense import (
    AdaptiveWindowHydrator,
    ConversationSourceKind,
    HydrationDetailLevel,
    LineageNode,
    LineageRootDedupEngine,
    SourceAwareDemotionEngine,
    SourceDemotionPolicy,
    run_lineage_defense_pipeline,
)


@pytest.fixture
def sample_candidates() -> list[LineageNode]:
    now = datetime.now(UTC)
    return [
        LineageNode(
            session_id="cron_sync_daily_01",
            lineage_root_id="cron_sync_daily_01",
            generation=1,
            source_kind=ConversationSourceKind.CRON_SCHEDULED,
            title="Scheduled Daily Repo Check",
            raw_score=0.92,
            messages_context=[
                "SYSTEM: Scheduled cron trigger.",
                "CHECK: Repository sync completed successfully.",
            ],
            updated_at=now,
        ),
        LineageNode(
            session_id="user_chat_architecture_v1",
            lineage_root_id="root_user_chat_architecture",
            generation=1,
            source_kind=ConversationSourceKind.INTERACTIVE,
            title="Decoupled Architecture Discussion v1",
            raw_score=0.85,
            messages_context=[
                "USER: How should we structure the memory layer?",
                "AGENT: We should separate harness from business facades.",
            ],
            updated_at=now,
        ),
        LineageNode(
            session_id="user_chat_architecture_v2",
            lineage_root_id="root_user_chat_architecture",
            generation=2,
            parent_id="user_chat_architecture_v1",
            source_kind=ConversationSourceKind.INTERACTIVE,
            title="Decoupled Architecture Discussion v2 Compaction",
            raw_score=0.88,
            messages_context=[
                "SUMMARY: Previous discussion agreed on clean separation.",
                "USER: Let's finalize the DTO contracts today.",
                "AGENT: Here are the typed Pydantic models.",
            ],
            updated_at=now,
        ),
        LineageNode(
            session_id="internal_subagent_task_99",
            lineage_root_id="subagent_task_99",
            generation=1,
            source_kind=ConversationSourceKind.INTERNAL_WORKER,
            title="Internal worker temporary scrape",
            raw_score=0.95,
            messages_context=["WORKER: Scraping docs..."],
            updated_at=now,
        ),
    ]


def test_automation_source_demotion_prioritizes_interactive_over_cron(
    sample_candidates: list[LineageNode],
) -> None:
    engine = SourceAwareDemotionEngine(
        policy=SourceDemotionPolicy(cron_weight_multiplier=0.45, hide_internal_workers=True)
    )
    result = engine.apply_demotion(sample_candidates, include_internal=False)

    # Internal worker should be suppressed
    assert not any(n.source_kind == ConversationSourceKind.INTERNAL_WORKER for n in result)

    # Interactive session should beat cron session in final score
    interactive_hit = next(n for n in result if n.session_id == "user_chat_architecture_v2")
    cron_hit = next(n for n in result if n.session_id == "cron_sync_daily_01")

    assert interactive_hit.final_score == 0.88
    # Cron raw_score 0.92 * 0.45 = 0.414
    assert cron_hit.final_score == 0.414
    # Top rank must be the interactive node, resolving Recall Blindness
    assert result[0].source_kind == ConversationSourceKind.INTERACTIVE


def test_cron_retained_when_only_match() -> None:
    cron_only = [
        LineageNode(
            session_id="cron_cleanup_01",
            lineage_root_id="cron_cleanup_01",
            generation=1,
            source_kind=ConversationSourceKind.CRON_SCHEDULED,
            title="Midnight Vacuum Cleanup",
            raw_score=0.75,
            messages_context=["VACUUM: Cleared 50 temp records."],
        )
    ]
    engine = SourceAwareDemotionEngine()
    result = engine.apply_demotion(cron_only)

    assert len(result) == 1
    assert result[0].session_id == "cron_cleanup_01"
    assert result[0].final_score < 0.75  # Penalized but retained!


def test_internal_worker_hidden_by_default_and_revealed_on_flag(
    sample_candidates: list[LineageNode],
) -> None:
    engine = SourceAwareDemotionEngine()

    # Default hidden
    hidden_run = engine.apply_demotion(sample_candidates, include_internal=False)
    assert not any(n.source_kind == ConversationSourceKind.INTERNAL_WORKER for n in hidden_run)

    # Explicitly included
    revealed_run = engine.apply_demotion(sample_candidates, include_internal=True)
    assert any(n.source_kind == ConversationSourceKind.INTERNAL_WORKER for n in revealed_run)


def test_lineage_generational_deduplication(sample_candidates: list[LineageNode]) -> None:
    dedup_engine = LineageRootDedupEngine()
    dedup_result = dedup_engine.deduplicate(sample_candidates)

    # The 2 architecture sessions share lineage_root_id="root_user_chat_architecture"
    # Generation 2 should be preserved, Generation 1 collapsed
    primary_ids = [n.session_id for n in dedup_result.primary_nodes]
    assert "user_chat_architecture_v2" in primary_ids
    assert "user_chat_architecture_v1" not in primary_ids

    assert dedup_result.collapsed_count_map["user_chat_architecture_v2"] == 1
    assert dedup_result.collapsed_ids_map["user_chat_architecture_v2"] == [
        "user_chat_architecture_v1"
    ]


def test_adaptive_window_hydration_token_savings(sample_candidates: list[LineageNode]) -> None:
    dedup_engine = LineageRootDedupEngine()
    hydrator = AdaptiveWindowHydrator(window_size=3)

    dedup_result = dedup_engine.deduplicate(sample_candidates)
    hits = hydrator.hydrate_hits(dedup_result, max_hits=3)

    assert len(hits) >= 2
    # Top 1 hit is expanded window
    assert hits[0].detail_level == HydrationDetailLevel.EXPANDED_WINDOW
    assert len(hits[0].window_messages) > 0

    # Top 2..N are compact cards
    for hit in hits[1:]:
        assert hit.detail_level == HydrationDetailLevel.COMPACT_CARD
        assert len(hit.window_messages) == 0

    # Audit report verifies substantial token savings
    report = hydrator.generate_audit_report(sample_candidates, sample_candidates, hits)
    assert report.token_saving_percent > 40.0
    assert report.estimated_tokens_saved > 0
    assert report.collapsed_lineage_count >= 1


def test_end_to_end_pipeline_facade(sample_candidates: list[LineageNode]) -> None:
    hits, report = run_lineage_defense_pipeline(
        sample_candidates,
        include_internal=False,
        max_hits=5,
    )

    assert len(hits) == 2  # 1 interactive root + 1 cron root (internal worker hidden)
    assert hits[0].source_kind == ConversationSourceKind.INTERACTIVE
    assert hits[0].collapsed_generations_count == 1
    assert report.hidden_internal_count == 1
    assert report.demoted_cron_count == 1
    assert report.interactive_top1_ratio == 1.0
