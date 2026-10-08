# [INPUT]: CachePartitionedContextBundle, CachePreservingEventEnvelopeAndColdStartHydrationSuite, CachePreservingEventEnvelopeProtocol, CachePreservingEventSuite, DormantSnapshot, EventAuditRecord, EventAuditTrailManager, EventEnvelopePayload, EventSourceTier, HydrationState, SandboxedSleepWakeLifecycleEngine
# [OUTPUT]: test_cache_preserving_event_suite.py
# [POS]: tests/agent/context_management/test_cache_preserving_event_suite.py

"""Unit test suite for CachePreservingEventEnvelopeAndColdStartHydrationSuite (Item 316).

Verifies:
1. Cache-preserving event envelope protocol isolating dynamic payloads at message tail and keeping projected cache hit >= 90%.
2. Sandboxed sleep-wake lifecycle engine creating <10MB snapshots and hydrating within 500ms budget.
3. Event audit trail manager decoupling high-frequency raw events from user conversation stream.
4. End-to-end facade coordinating envelope generation, dual-tier context partitioning, sleep-wake, and audit trail.
"""

from __future__ import annotations

import time
import pytest

from myrm_agent_harness.agent.context_management.event_cache_preservation import (
    CachePartitionedContextBundle,
    CachePreservingEventEnvelopeAndColdStartHydrationSuite,
    CachePreservingEventEnvelopeProtocol,
    CachePreservingEventSuite,
    DormantSnapshot,
    EventAuditRecord,
    EventAuditTrailManager,
    EventEnvelopePayload,
    EventSourceTier,
    HydrationState,
    SandboxedSleepWakeLifecycleEngine,
)


def test_cache_preserving_protocol_tail_frame_and_hit_ratio() -> None:
    protocol = CachePreservingEventEnvelopeProtocol()

    # Static prefix with persona, rules, and MCP tool schemas (~2000 chars)
    static_prefix = (
        "# System Persona & Guardrails\nYou are an expert architect.\n"
        "## MCP Tool Definitions\n- tool_a: query database\n- tool_b: fetch telemetry\n"
        * 15
    )

    history = [
        "User: Check system status.",
        "Assistant: Running baseline diagnostic sweep.",
    ]

    event = EventEnvelopePayload(
        event_id="evt-9901",
        source=EventSourceTier.MCP_PUSH_EVENT,
        timestamp_iso="2026-10-08T10:00:00Z",
        priority="high",
        payload_text='{"alert": "CPU spike on worker 3", "cpu_percent": 94.2}',
    )

    bundle = protocol.partition_context(
        static_prefix=static_prefix,
        conversation_history=history,
        event_payload=event,
    )

    # Verify static prefix is untouched at byte 0
    full_prompt = bundle.render_full_prompt()
    assert protocol.verify_prefix_unmodified(static_prefix, full_prompt) is True
    assert full_prompt.startswith(static_prefix.strip())

    # Verify event frame is at the very tail
    assert "<event_trigger id=\"evt-9901\"" in bundle.ephemeral_event_frame
    assert "CPU spike on worker 3" in bundle.ephemeral_event_frame
    assert full_prompt.endswith("</event_trigger>")

    # Projected cache hit ratio must exceed 90% (0.90)
    assert bundle.cache_hit_ratio_projected >= 0.90
    assert bundle.prefix_tokens_estimate > bundle.event_tokens_estimate


def test_sandboxed_sleep_wake_lifecycle_engine_freeze_and_hydrate() -> None:
    engine = SandboxedSleepWakeLifecycleEngine()
    assert engine.current_state == HydrationState.ACTIVE_RUNNING

    session_id = "session-test-42"
    static_prefix = "# System Persona\nImmutable instructions.\n"
    history = ["User: Build project.", "Assistant: Compiling modules."]

    # Create dormant snapshot
    snapshot = engine.create_dormant_snapshot(
        session_id=session_id,
        static_prefix=static_prefix,
        conversation_history=history,
    )

    assert engine.current_state == HydrationState.DORMANT_SLEEP
    assert snapshot.session_id == session_id
    assert snapshot.serialized_state_bytes < 10 * 1024 * 1024  # <10MB budget
    assert snapshot.cached_prefix_text == static_prefix
    assert snapshot.history_turns_count == 2

    # Wake and hydrate on incoming event
    incoming_event = EventEnvelopePayload(
        event_id="evt-1002",
        source=EventSourceTier.WEBHOOK_SYSTEM,
        timestamp_iso="2026-10-08T10:05:00Z",
        priority="critical",
        payload_text="Payment gateway webhook acknowledged",
    )

    bundle, elapsed_ms = engine.hydrate_and_wake(
        snapshot=snapshot,
        conversation_history=history,
        incoming_event=incoming_event,
    )

    # Sub-500ms requirement (typically < 10ms in local memory)
    assert elapsed_ms < 500.0
    assert engine.current_state == HydrationState.ACTIVE_RUNNING
    assert "Payment gateway webhook" in bundle.ephemeral_event_frame
    assert bundle.static_prefix_tier == static_prefix.strip()


def test_event_audit_trail_manager_isolation_and_promotion() -> None:
    manager = EventAuditTrailManager(max_audit_entries=50)

    # 1. Normal background telemetry event -> Not promoted to human chat
    telemetry_evt = EventEnvelopePayload(
        event_id="evt-telemetry-1",
        source=EventSourceTier.TIMER_CRON,
        timestamp_iso="2026-10-08T10:10:00Z",
        priority="low",
        payload_text="Heartbeat ping ok",
    )
    rec1 = manager.record_event(telemetry_evt, summary="Routine ping")
    assert rec1.was_promoted_to_user is False

    # 2. Critical error alert -> Promoted to human chat
    critical_evt = EventEnvelopePayload(
        event_id="evt-alert-2",
        source=EventSourceTier.WEBHOOK_SYSTEM,
        timestamp_iso="2026-10-08T10:11:00Z",
        priority="critical",
        payload_text="Disk /dev/sda1 full 100%",
    )
    rec2 = manager.record_event(critical_evt, summary="Disk full critical error")
    assert rec2.was_promoted_to_user is True

    # Check listing
    all_records = manager.list_audit_trail()
    assert len(all_records) == 2

    promoted_only = manager.list_audit_trail(only_promoted=True)
    assert len(promoted_only) == 1
    assert promoted_only[0].event_id == "evt-alert-2"


def test_cache_preserving_suite_end_to_end_facade() -> None:
    suite = CachePreservingEventEnvelopeAndColdStartHydrationSuite()

    # Standard 1024-token aligned static prefix containing system persona and MCP schemas
    static_prefix = "# Persona Core\nDeterministic baseline.\n" * 80
    history = ["User: Start deployment pipeline.", "Assistant: Pipeline job triggered."]

    # Step 1: Create event envelope
    event = suite.create_event_envelope(
        payload_text="CI Pipeline finished with status: SUCCESS",
        source=EventSourceTier.MCP_PUSH_EVENT,
        priority="high",
        event_id="ci-901",
    )
    assert event.event_id == "ci-901"
    assert event.source == EventSourceTier.MCP_PUSH_EVENT

    # Step 2: Partition context
    bundle = suite.partition_context(
        static_prefix=static_prefix,
        conversation_history=history,
        event_envelope=event,
    )
    assert bundle.cache_hit_ratio_projected >= 0.90
    assert "ci-901" in bundle.ephemeral_event_frame

    # Step 3: Hibernate sandbox during inactive window
    snapshot = suite.freeze_dormant_sandbox(
        session_id="deploy-sess-1",
        static_prefix=static_prefix,
        conversation_history=history,
    )
    assert snapshot.session_id == "deploy-sess-1"

    # Step 4: Wake and hydrate in sub-500ms
    new_event = suite.create_event_envelope(
        payload_text="Follow-up release tag v1.4.0 created",
        source=EventSourceTier.WEBHOOK_SYSTEM,
        priority="normal",
    )
    hydrated_bundle, elapsed_ms = suite.wake_and_hydrate(
        snapshot=snapshot,
        conversation_history=history,
        incoming_event=new_event,
    )
    assert elapsed_ms < 500.0
    assert "Follow-up release tag v1.4.0" in hydrated_bundle.ephemeral_event_frame

    # Step 5: Audit record logging
    audit = suite.record_and_evaluate_audit(new_event, summary="Tag v1.4.0 created")
    assert audit.event_id == new_event.event_id

    records = suite.list_audit_records()
    assert len(records) >= 1

    # Verify alias
    assert CachePreservingEventSuite is CachePreservingEventEnvelopeAndColdStartHydrationSuite
