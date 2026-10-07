from __future__ import annotations

import pytest

from myrm_agent_harness.agent.artifacts import (
    ProgressStep,
    StepExecutionStatus,
    WorkNotesSnapshot,
)
from myrm_agent_harness.runtime.context import (
    ArchivedMessageRecord,
    ArchiveMessageRoleKind,
    CognitiveActionGuidance,
    ContextCognitiveSnapshot,
    ContextUrgencyLevel,
    FailureRootCauseKind,
    InMemorySessionArchiveStore,
    NegativeDecisionLedger,
    ThreeTierMemoryFunnelAggregator,
)


@pytest.fixture
def aggregator() -> ThreeTierMemoryFunnelAggregator:
    return ThreeTierMemoryFunnelAggregator()


def test_full_pipeline_three_tier_memory_funnel_aggregation(
    aggregator: ThreeTierMemoryFunnelAggregator,
) -> None:
    session_id = "session-test-three-tier"

    # 1. Layer 1 Cognitive snapshot mock
    cog_snapshot = ContextCognitiveSnapshot(
        total_limit_tokens=128_000,
        used_tokens=48_000,
        remaining_tokens=80_000,
        capacity_pct=37.5,
        urgency_level=ContextUrgencyLevel.NOMINAL,
        suggested_action=CognitiveActionGuidance.EXPLORE_FREELY,
        estimated_remaining_turns=40,
        is_compaction_imminent=False,
        gauge_rendered_bar="[████░░░░░░] 37.5%",
        guidance_message="Capacity abundant, explore freely.",
    )

    # 2. Layer 2 WorkNotes snapshot & Negative ledger
    notes = WorkNotesSnapshot(
        goal="迁移认证架构至 JWT",
        current_step_index=1,
        steps=[
            ProgressStep(step_index=0, description="设计 Token Schema", status=StepExecutionStatus.COMPLETED),
            ProgressStep(step_index=1, description="实现签发中间件", status=StepExecutionStatus.IN_PROGRESS),
        ],
        key_findings=["HS256 签名速度极快"],
        disqualified_approaches=["不要在 URL 中传递 token"],
        todos=["补充刷新黑名单"],
    )

    ledger = NegativeDecisionLedger()
    ledger.record_rejection(
        session_id=session_id,
        attempted_solution="使用 Cookie 存储明文 JWT",
        root_cause_kind=FailureRootCauseKind.SECURITY_VIOLATION,
        rejection_reason="存在 XSS 窃取风险",
        disqualified_patterns=["明文存储 JWT"],
    )

    # 3. Layer 3 Archive store
    archive_store = InMemorySessionArchiveStore()
    archive_store.append(
        ArchivedMessageRecord(
            record_id="rec-001",
            session_id=session_id,
            turn_index=0,
            role=ArchiveMessageRoleKind.USER,
            content="搭建系统",
            timestamp_iso="2026-10-07T10:00:00Z",
        )
    )
    archive_store.append(
        ArchivedMessageRecord(
            record_id="rec-002",
            session_id=session_id,
            turn_index=1,
            role=ArchiveMessageRoleKind.ASSISTANT,
            content="系统已就绪",
            timestamp_iso="2026-10-07T10:01:00Z",
        )
    )

    res = aggregator.aggregate(
        session_id=session_id,
        cognitive_snapshot=cog_snapshot,
        active_turns_count=4,
        notes_snapshot=notes,
        negative_ledger=ledger,
        archive_store=archive_store,
    )

    assert res.session_id == session_id

    # Layer 1 checks
    wb = res.active_workbench
    assert wb.active_turns_count == 4
    assert wb.current_tokens == 48_000
    assert wb.token_limit == 128_000
    assert wb.capacity_percentage == 37.5
    assert wb.urgency_level == "nominal"
    assert wb.guidance == "EXPLORE_FREELY"

    # Layer 2 checks
    stage = res.stage_notes_and_ledger
    assert stage.goal == "迁移认证架构至 JWT"
    assert stage.current_step_index == 1
    assert "设计 Token Schema" in stage.completed_milestones
    assert "HS256 签名速度极快" in stage.key_findings
    assert "不要在 URL 中传递 token" in stage.disqualified_patterns
    assert "明文存储 JWT" in stage.disqualified_patterns
    assert "补充刷新黑名单" in stage.pending_todos

    # Layer 3 checks
    arch = res.searchable_archive
    assert arch.total_archived_turns == 2
    assert arch.searchable is True


def test_graceful_degradation_with_none_components(
    aggregator: ThreeTierMemoryFunnelAggregator,
) -> None:
    session_id = "session-empty"
    res = aggregator.aggregate(session_id=session_id)

    assert res.session_id == session_id
    assert res.active_workbench.active_turns_count == 0
    assert res.active_workbench.current_tokens == 0
    assert res.active_workbench.urgency_level == "nominal"
    assert res.stage_notes_and_ledger.goal == ""
    assert len(res.stage_notes_and_ledger.disqualified_patterns) == 0
    assert res.searchable_archive.total_archived_turns == 0
    assert res.searchable_archive.searchable is True
