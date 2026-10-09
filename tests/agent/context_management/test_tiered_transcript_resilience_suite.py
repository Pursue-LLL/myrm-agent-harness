# [INPUT]: TieredTranscriptOffloadingAndSessionLifecycleResilienceSuite, TwoTierTranscriptOffloader, SingleFlightRefreshGate, DelayedSlotAllocator, DynamicCliCredentialEngine, types from transcript_resilience
# [OUTPUT]: test_tiered_transcript_resilience_suite
# [POS]: tests.agent.context_management.test_tiered_transcript_resilience_suite
"""Unit test suite for Tiered Transcript Offloading & Lifecycle Resilience (Item 333).

Verifies bounded-heap transcript offloading and on-demand hydration, single-flight
refresh mutex gate, lazy slot reservation contracts, and dynamic CLI vault credentials.
"""

from __future__ import annotations

import sys
import threading
import time
import pytest

from myrm_agent_harness.agent.context_management.transcript_resilience import (
    DEFAULT_MAX_CONCURRENCY_SLOTS,
    DEFAULT_MAX_VIEWPORT_MESSAGES,
    DelayedSessionSlot,
    DelayedSlotAllocator,
    DynamicCliCredentialEngine,
    DynamicCredentialSpec,
    HydratedTranscriptMessage,
    SingleFlightRefreshGate,
    SingleFlightTokenState,
    TieredTranscriptOffloadingAndSessionLifecycleResilienceSuite,
    TranscriptResilienceConfig,
    TranscriptStubRecord,
    TwoTierTranscriptOffloader,
    compute_payload_hash,
    format_active_slot_hud,
)


def test_compute_payload_hash_deterministic() -> None:
    """Ensure SHA-256 message payload fingerprint calculation is deterministic."""
    h1 = compute_payload_hash("user", "Hello world", None)
    h2 = compute_payload_hash("user", "Hello world", [])
    assert h1 == h2
    assert len(h1) == 64

    h3 = compute_payload_hash("assistant", "Hello world", None)
    assert h1 != h3


def test_two_tier_transcript_offloading_and_hydration() -> None:
    """Ensure oldest messages exceeding viewport are stubbed and can be hydrated on-demand."""
    offloader = TwoTierTranscriptOffloader(max_viewport_size=3)
    session_id = "sess_offload_test"

    # Append 5 messages
    for i in range(1, 6):
        offloader.append_message(
            session_id=session_id,
            msg_id=f"msg_{i}",
            role="user" if i % 2 == 1 else "assistant",
            content=f"Message content number {i}" + (" and extra verbose payload" * 5),
            tool_calls=[{"id": f"call_{i}", "name": "test_tool"}] if i % 2 == 0 else [],
            created_at_iso=f"2026-10-09T08:0{i}:00Z",
        )

    # Total message count should be 5
    assert offloader.get_total_message_count(session_id) == 5

    # Active viewport should retain exactly the 3 most recent messages (msg_3, msg_4, msg_5)
    viewport = offloader.get_viewport_messages(session_id)
    assert len(viewport) == 3
    assert [m.msg_id for m in viewport] == ["msg_3", "msg_4", "msg_5"]

    # Exactly 2 older messages (msg_1, msg_2) should be converted to lightweight stubs
    stubs = offloader.get_stubs(session_id)
    assert len(stubs) == 2
    assert [s.msg_id for s in stubs] == ["msg_1", "msg_2"]
    assert len(stubs[0].original_payload_hash) == 64
    assert stubs[1].has_tool_calls is True

    # Hydrate stubbed message on-demand from backing vault
    hydrated_1 = offloader.hydrate_message(session_id, "msg_1")
    assert hydrated_1 is not None
    assert hydrated_1.msg_id == "msg_1"
    assert "Message content number 1" in hydrated_1.content

    # Clear session
    offloader.clear_session(session_id)
    assert offloader.get_total_message_count(session_id) == 0


def test_single_flight_refresh_gate_coordination() -> None:
    """Ensure multiple concurrent 401 requests trigger only one refresh and share the new token."""
    gate = SingleFlightRefreshGate(initial_token="expired_token", timeout_seconds=4.0)

    call_count = 0
    call_lock = threading.Lock()

    def _mock_refresh() -> str:
        nonlocal call_count
        with call_lock:
            call_count += 1
        time.sleep(0.1)  # Simulate network latency
        return "brand_new_refreshed_token_xyz"

    results: list[str] = []
    threads: list[threading.Thread] = []

    def _worker() -> None:
        token = gate.execute_with_refresh(_mock_refresh)
        results.append(token)

    for _ in range(5):
        t = threading.Thread(target=_worker)
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    # All 5 requests must receive the identical refreshed token
    assert len(results) == 5
    assert all(r == "brand_new_refreshed_token_xyz" for r in results)
    # The refresh function must have been executed strictly once by the Leader!
    assert call_count == 1

    state = gate.get_state()
    assert state.access_token == "brand_new_refreshed_token_xyz"
    assert state.is_refreshing is False


def test_single_flight_refresh_gate_leader_error_propagation() -> None:
    """Ensure exceptions raised by the leader are cleanly propagated to waiting callers."""
    gate = SingleFlightRefreshGate(initial_token="old_tok", timeout_seconds=3.0)

    def _failing_refresh() -> str:
        time.sleep(0.05)
        raise PermissionError("Refresh token revoked by IdP")

    with pytest.raises(PermissionError) as exc_info:
        gate.execute_with_refresh(_failing_refresh)
    assert "Refresh token revoked by IdP" in str(exc_info.value)
    assert gate.get_state().is_refreshing is False


def test_delayed_slot_allocator_contract() -> None:
    """Ensure lazy slot reservation, token tracking, capacity limits, and HUD rendering work."""
    allocator = DelayedSlotAllocator(max_concurrency_slots=2)

    # 1. Claim slot for session A
    slot_a = allocator.claim_slot("session_A", holder_name="Coder Agent")
    assert slot_a.is_claimed is True
    assert slot_a.session_id == "session_A"
    assert allocator.active_slots_count == 1
    assert allocator.is_slot_claimed("session_A") is True

    # 2. Idempotent claim
    slot_a_repeat = allocator.claim_slot("session_A", holder_name="Coder Agent")
    assert slot_a_repeat.session_id == "session_A"
    assert allocator.active_slots_count == 1

    # 3. Claim slot for session B
    slot_b = allocator.claim_slot("session_B", holder_name="Tester Agent")
    assert slot_b.session_id == "session_B"
    assert allocator.active_slots_count == 2

    # 4. Exceed capacity (capacity is 2)
    with pytest.raises(RuntimeError) as exc_info:
        allocator.claim_slot("session_C", holder_name="Docs Agent")
    assert "Concurrency capacity exhausted" in str(exc_info.value)

    # 5. Record tokens
    allocator.record_token_usage("session_A", tokens=2500)
    slots = allocator.get_active_slots()
    slot_a_record = next(s for s in slots if s.session_id == "session_A")
    assert slot_a_record.tokens_consumed == 2500

    # 6. Format HUD
    hud_text = allocator.get_hud_summary()
    assert "=== CONCURRENCY SLOTS HUD [2/2] ===" in hud_text
    assert "session_A" in hud_text
    assert "Coder Agent" in hud_text
    assert "2500" in hud_text

    # 7. Release slot A and re-claim for C
    released = allocator.release_slot("session_A")
    assert released is True
    assert allocator.is_slot_claimed("session_A") is False
    assert allocator.active_slots_count == 1

    slot_c = allocator.claim_slot("session_C", holder_name="Docs Agent")
    assert slot_c.session_id == "session_C"
    assert allocator.active_slots_count == 2


def test_dynamic_cli_credential_engine_evaluation() -> None:
    """Ensure secure subprocess execution, output parsing, and caching."""
    engine = DynamicCliCredentialEngine()

    # Test pure token stdout using python -c print
    spec_pure = DynamicCredentialSpec(
        command_args=[sys.executable, "-c", "print('sk-proj-test12345678')"],
        cache_ttl_seconds=60.0,
    )
    token1 = engine.resolve_credential(spec_pure)
    assert token1 == "sk-proj-test12345678"

    # Cached evaluation (should return immediately)
    token1_cached = engine.resolve_credential(spec_pure)
    assert token1_cached == "sk-proj-test12345678"

    # Test KEY=VALUE format
    spec_kv = DynamicCredentialSpec(
        command_args=[sys.executable, "-c", "print('OPENAI_API_KEY=sk-ant-99998888')"],
        cache_ttl_seconds=60.0,
    )
    token2 = engine.resolve_credential(spec_kv)
    assert token2 == "sk-ant-99998888"

    # Test error handling on non-zero exit
    spec_failing = DynamicCredentialSpec(
        command_args=[sys.executable, "-c", "import sys; sys.stderr.write('Key not found'); sys.exit(2)"],
        cache_ttl_seconds=60.0,
    )
    with pytest.raises(RuntimeError) as exc_info:
        engine.resolve_credential(spec_failing)
    assert "CLI vault command" in str(exc_info.value)
    assert "Key not found" in str(exc_info.value)


def test_tiered_transcript_resilience_suite_facade() -> None:
    """Ensure high-level facade coordinates transcript offloading, refresh gate, and slot HUD."""
    config = TranscriptResilienceConfig(
        max_viewport_messages=2,
        max_concurrency_slots=3,
        single_flight_timeout_seconds=5.0,
    )
    suite = TieredTranscriptOffloadingAndSessionLifecycleResilienceSuite(config=config)
    session_id = "suite_sess_01"

    # 1. Lazy slot reservation
    slot = suite.claim_slot(session_id, holder_name="Main Assistant")
    assert slot.is_claimed is True

    # 2. Append messages causing viewport offload
    suite.record_message(session_id, "m1", "user", "Hello first")
    suite.record_message(session_id, "m2", "assistant", "Hello second")
    suite.record_message(session_id, "m3", "user", "Hello third")

    viewport = suite.get_viewport_messages(session_id)
    assert len(viewport) == 2
    assert [m.msg_id for m in viewport] == ["m2", "m3"]

    stubs = suite.get_stubs(session_id)
    assert len(stubs) == 1
    assert stubs[0].msg_id == "m1"

    # 3. Hydrate
    hydrated = suite.hydrate_message(session_id, "m1")
    assert hydrated is not None
    assert hydrated.content == "Hello first"

    # 4. Single-flight token execution
    tok = suite.execute_with_single_flight_refresh(lambda: "new_token_777")
    assert tok == "new_token_777"
    assert suite.get_token_state().access_token == "new_token_777"

    # 5. Check HUD
    hud = suite.get_active_slot_hud()
    assert "Main Assistant" in hud
    assert "suite_sess_01" in hud

    # 6. Clear session
    suite.clear_session(session_id)
    assert len(suite.get_viewport_messages(session_id)) == 0
    assert len(suite.get_stubs(session_id)) == 0
    assert "suite_sess_01" not in suite.get_active_slot_hud()
