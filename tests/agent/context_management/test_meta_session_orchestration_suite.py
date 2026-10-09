# [INPUT]: MetaSessionOrchestrationAndChatCoworkDualTrackFusionSuite, DualTrackMemoryBus, HierarchicalMetaSessionOrchestrator, SubSessionFaultIsolator, types from meta_session_orchestration
# [OUTPUT]: test_meta_session_orchestration_suite
# [POS]: tests.agent.context_management.test_meta_session_orchestration_suite
"""Unit test suite for Meta-Session Orchestration & Dual-Track Fusion (Item 332).

Verifies hierarchical session dispatching, Chat-Cowork bidirectional memory bus,
sub-session crash isolation, realtime progress HUD generation, and session lifecycle.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.context_management.meta_session_orchestration import (
    DEFAULT_MAX_CONCURRENT_SUBSESSIONS,
    DualTrackMemoryBus,
    DualTrackMemoryEnvelope,
    HierarchicalMetaSessionOrchestrator,
    MetaSessionConfig,
    MetaSessionOrchestrationAndChatCoworkDualTrackFusionSuite,
    SessionHierarchyType,
    SessionTrackMode,
    SubSessionFailureReport,
    SubSessionFaultIsolator,
    SubSessionHandoffDigest,
    SubSessionProgressCard,
    SubSessionStatus,
    SubSessionTaskDescriptor,
    compute_digest_hash,
    compute_envelope_hash,
    format_dual_track_prompt_block,
    format_meta_progress_hud,
)


def _make_sample_descriptor(
    meta_id: str = "meta_001",
    task_id: str = "sub_task_101",
    title: str = "Database Schema Migration",
) -> SubSessionTaskDescriptor:
    """Helper creating a standard sub-session task descriptor."""
    return SubSessionTaskDescriptor(
        task_id=task_id,
        meta_session_id=meta_id,
        title=title,
        goal_description="Refactor user table to support hierarchical multi-tenancy",
        parameters={"dry_run": False, "target_version": 4},
        target_track=SessionTrackMode.COWORK,
        created_at_iso="2026-10-09T08:00:00Z",
    )


def test_orchestration_types_and_hashing() -> None:
    """Ensure data model contracts and deterministic hash algorithms work accurately."""
    descriptor = _make_sample_descriptor()
    assert descriptor.meta_session_id == "meta_001"
    assert descriptor.target_track == SessionTrackMode.COWORK

    env_hash = compute_envelope_hash(
        meta_session_id="meta_001",
        user_intent="Refactor authentication",
        working_summary="JWT migration in progress",
        track_mode=SessionTrackMode.CHAT,
    )
    assert len(env_hash) == 64

    digest_hash = compute_digest_hash(
        task_id="sub_001",
        meta_session_id="meta_001",
        outcome_summary="All migrations completed",
        deliverables=["src/db/models.py", "migrations/004.sql"],
    )
    assert len(digest_hash) == 64


def test_dual_track_memory_bus_projection_and_sinking() -> None:
    """Ensure Chat intention projection and Cowork deliverable sinking synchronize smoothly."""
    bus = DualTrackMemoryBus()
    meta_id = "meta_session_finance"

    # 1. Project Chat intention into Cowork
    chat_env = bus.project_chat_to_cowork(
        meta_session_id=meta_id,
        user_intent="Generate Q3 cash flow forecasting report",
        preferences={"currency": "USD", "style": "markdown_table"},
        constraints=["Preserve existing audit trail", "No external network access"],
        working_summary="User requested quarterly financial reconciliation",
    )
    assert chat_env.track_mode == SessionTrackMode.CHAT
    assert chat_env.user_intent == "Generate Q3 cash flow forecasting report"
    assert chat_env.preferences.get("currency") == "USD"
    assert len(chat_env.envelope_hash) == 64

    # 2. Sink Cowork handoff brief back to meta
    digest = SubSessionHandoffDigest(
        task_id="worker_finance_01",
        meta_session_id=meta_id,
        title="Q3 Cash Flow Compiler",
        outcome_summary="Aggregated 3 months of bank statements into markdown report",
        deliverables=["reports/q3_cash_flow.md"],
        lessons_learned=["Pre-filter zero-value ledger adjustments"],
        digest_hash="a" * 64,
    )
    cowork_env = bus.sink_cowork_to_meta(
        meta_session_id=meta_id,
        handoff_digest=digest,
    )
    assert cowork_env.track_mode == SessionTrackMode.COWORK
    assert "reports/q3_cash_flow.md" in cowork_env.generated_artifacts

    # 3. Retrieve and format prompt block
    envelopes = bus.get_envelopes(meta_id)
    assert len(envelopes) == 2
    prompt_block = format_dual_track_prompt_block(envelopes)
    assert "=== DUAL-TRACK UNIFIED MEMORY BUS EVIDENCE ===" in prompt_block
    assert "Source Track: CHAT" in prompt_block
    assert "Source Track: COWORK" in prompt_block
    assert "reports/q3_cash_flow.md" in prompt_block

    # 4. Clear session
    bus.clear_session(meta_id)
    assert len(bus.get_envelopes(meta_id)) == 0


def test_sub_session_fault_isolator_recovery_strategy() -> None:
    """Ensure worker sub-session exceptions are isolated with intelligent recovery suggestions."""
    isolator = SubSessionFaultIsolator(max_allowed_retries=2)
    meta_id = "meta_fault_test"
    task_id = "task_worker_99"

    # 1. First transient timeout -> retry
    timeout_err = TimeoutError("Network connection timed out after 30s")
    rep1 = isolator.isolate_failure(task_id=task_id, meta_session_id=meta_id, exc=timeout_err)
    assert rep1.is_isolated is True
    assert rep1.error_type == "TimeoutError"
    assert rep1.suggested_recovery == "retry"
    assert isolator.get_retry_count(meta_id, task_id) == 1

    # 2. Second transient timeout -> retry
    rep2 = isolator.isolate_failure(task_id=task_id, meta_session_id=meta_id, exc=timeout_err)
    assert rep2.suggested_recovery == "retry"
    assert isolator.get_retry_count(meta_id, task_id) == 2

    # 3. Third timeout (retry exceeded) -> degrade
    rep3 = isolator.isolate_failure(task_id=task_id, meta_session_id=meta_id, exc=timeout_err)
    assert rep3.suggested_recovery == "degrade"

    # 4. Permission error -> parent_takeover
    perm_err = PermissionError("Forbidden: write permission denied on /etc/system.conf")
    rep4 = isolator.isolate_failure(
        task_id="task_perm", meta_session_id=meta_id, exc=perm_err
    )
    assert rep4.suggested_recovery == "parent_takeover"

    # 5. History retrieval and cleanup
    history = isolator.get_failure_reports(meta_id)
    assert len(history) == 4
    isolator.clear_session(meta_id)
    assert len(isolator.get_failure_reports(meta_id)) == 0


def test_hierarchical_meta_orchestrator_lifecycle() -> None:
    """Ensure sub-sessions are dispatched, tracked, completed, and aggregated into progress HUD."""
    config = MetaSessionConfig(max_concurrent_sub_sessions=2)
    orchestrator = HierarchicalMetaSessionOrchestrator(config=config)
    meta_id = "meta_orchestrator_run"

    # 1. Dispatch first task
    desc1 = _make_sample_descriptor(meta_id=meta_id, task_id="task_1", title="Build API Backend")
    card1 = orchestrator.dispatch_sub_session(desc1)
    assert card1.status == SubSessionStatus.RUNNING
    assert card1.title == "Build API Backend"

    # 2. Dispatch second task
    desc2 = _make_sample_descriptor(meta_id=meta_id, task_id="task_2", title="Build Web UI")
    card2 = orchestrator.dispatch_sub_session(desc2)
    assert card2.status == SubSessionStatus.RUNNING

    # 3. Exceed concurrency limit
    desc3 = _make_sample_descriptor(meta_id=meta_id, task_id="task_3", title="Write Docs")
    with pytest.raises(RuntimeError) as exc_info:
        orchestrator.dispatch_sub_session(desc3)
    assert "reached max concurrent sub-sessions limit" in str(exc_info.value)

    # 4. Update progress
    updated_card1 = orchestrator.update_sub_session_progress(
        meta_session_id=meta_id,
        task_id="task_1",
        current_step="Compiling routes and schema definitions",
        active_tool="write_to_file",
        tokens_consumed=1500,
        add_completed_substep="Database models created",
    )
    assert updated_card1.active_tool == "write_to_file"
    assert updated_card1.tokens_consumed == 1500
    assert "Database models created" in updated_card1.completed_substeps

    # 5. Complete task_1
    final_card1, digest1 = orchestrator.complete_sub_session(
        meta_session_id=meta_id,
        task_id="task_1",
        outcome_summary="Backend REST APIs completed and verified with pytest",
        deliverables=["src/api/routes.py", "tests/test_routes.py"],
    )
    assert final_card1.status == SubSessionStatus.COMPLETED
    assert digest1.title == "Build API Backend"
    assert "src/api/routes.py" in digest1.deliverables

    # 6. Now task_3 can be dispatched since task_1 is COMPLETED
    card3 = orchestrator.dispatch_sub_session(desc3)
    assert card3.status == SubSessionStatus.RUNNING

    # 7. Fail task_2 and isolate
    fail_card2, fail_rep = orchestrator.fail_sub_session(
        meta_session_id=meta_id,
        task_id="task_2",
        exc=RuntimeError("Vite bundler failed with out of memory"),
    )
    assert fail_card2.status == SubSessionStatus.FAILED
    assert fail_rep.is_isolated is True
    assert "RuntimeError" in fail_card2.current_step

    # 8. Check HUD rendering
    all_cards = orchestrator.get_progress_cards(meta_id)
    assert len(all_cards) == 3
    hud_text = format_meta_progress_hud(all_cards)
    assert "=== META-SESSION MULTI-TASK PROGRESS HUD ===" in hud_text
    assert "[COMPLETED]" in hud_text
    assert "[FAILED]" in hud_text
    assert "[RUNNING]" in hud_text


def test_meta_session_fusion_suite_facade() -> None:
    """Ensure high-level facade coordinates memory bus, orchestrator, and HUD generation."""
    suite = MetaSessionOrchestrationAndChatCoworkDualTrackFusionSuite()
    meta_id = "meta_full_facade"

    # 1. Dispatch worker task with Chat context projection
    desc = _make_sample_descriptor(meta_id=meta_id, task_id="worker_extract", title="Extract Data")
    card = suite.dispatch_worker_task(
        descriptor=desc,
        chat_intent_projection="User wants CSV export of users table",
        user_preferences={"format": "csv", "delimiter": ","},
        constraints=["Do not expose password hashes"],
    )
    assert card.status == SubSessionStatus.RUNNING

    # Verify chat envelope exists in memory
    memory_prompt = suite.get_dual_track_memory_prompt(meta_id)
    assert "User wants CSV export of users table" in memory_prompt

    # 2. Update progress
    updated = suite.update_task_progress(
        meta_session_id=meta_id,
        task_id="worker_extract",
        current_step="Querying DB rows and masking sensitive columns",
        active_tool="db_query",
        tokens_consumed=820,
        completed_substep="Database connected",
    )
    assert updated.tokens_consumed == 820

    # 3. Complete task with auto-sinking into memory
    final_card, digest = suite.complete_worker_task(
        meta_session_id=meta_id,
        task_id="worker_extract",
        outcome_summary="Exported 10,000 sanitized user rows to CSV",
        deliverables=["/tmp/users_export.csv"],
    )
    assert final_card.status == SubSessionStatus.COMPLETED

    # Check that deliverable was automatically sinked into memory bus
    updated_memory_prompt = suite.get_dual_track_memory_prompt(meta_id)
    assert "Delivered Task 'Extract Data'" in updated_memory_prompt
    assert "/tmp/users_export.csv" in updated_memory_prompt

    # 4. Check HUD text
    hud = suite.get_meta_progress_hud(meta_id)
    assert "Extract Data (ID: worker_extract) | Status: [COMPLETED]" in hud

    # 5. Clear session
    suite.clear_session(meta_id)
    assert suite.get_meta_progress_hud(meta_id) == ""
    assert suite.get_dual_track_memory_prompt(meta_id) == ""
