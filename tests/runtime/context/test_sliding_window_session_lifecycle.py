"""Unit tests for sliding window session lifecycle manager and KV cache keeper."""

from __future__ import annotations

import concurrent.futures

from myrm_agent_harness.runtime.context.sliding_window_session_lifecycle import (
    InactivitySlidingWindowSessionManager,
    PrefixKvCacheStabilityKeeper,
    SessionMemoryCrystallizer,
)
from myrm_agent_harness.runtime.context.sliding_window_session_lifecycle_types import (
    InactivityWindowConfig,
    SessionLifecycleState,
)


def test_prefix_kv_cache_fingerprint_and_stability() -> None:
    """Verifies prefix fingerprint calculation, stability verification, and savings estimation."""
    keeper = PrefixKvCacheStabilityKeeper()
    sys_prompt = "You are a software architect agent."
    tools_doc = "tool: read_file\ntool: write_file"

    fp = keeper.compute_prefix_fingerprint(sys_prompt, tools_doc, current_time=1000.0)
    assert len(fp.prefix_hash) == 64
    assert fp.token_count > 0
    assert fp.is_frozen is True

    # Register initial prefix for session
    is_stable, msg = keeper.register_or_verify_prefix(
        "sess-1", f"{sys_prompt}\n---\n{tools_doc}", current_time=1000.0
    )
    assert is_stable is True
    assert "frozen" in msg

    # Identical prefix verification
    is_stable2, msg2 = keeper.register_or_verify_prefix(
        "sess-1", f"{sys_prompt}\n---\n{tools_doc}", current_time=1050.0
    )
    assert is_stable2 is True
    assert "100% KV Cache hit" in msg2

    # Drifted prefix verification
    drifted_prefix = f"{sys_prompt} modified!\n---\n{tools_doc}"
    is_stable3, msg3 = keeper.register_or_verify_prefix(
        "sess-1", drifted_prefix, current_time=1100.0
    )
    assert is_stable3 is False
    assert "Prefix drifted" in msg3

    # Savings calculation
    savings = keeper.estimate_cache_savings(prefix_tokens=2000, query_count=10, cache_discount_rate=0.85)
    assert savings["cached_queries"] == 9.0
    assert savings["saved_tokens"] == 2000 * 9 * 0.85
    assert savings["savings_ratio"] > 0.7


def test_inactivity_sliding_window_touch_and_extension() -> None:
    """Verifies session touch refreshing the inactivity window and state transitions."""
    config = InactivityWindowConfig(
        inactivity_timeout_seconds=72.0 * 3600.0,
        idle_warning_threshold_seconds=48.0 * 3600.0,
    )
    mgr = InactivitySlidingWindowSessionManager(config=config)

    t0 = 10000.0
    snap = mgr.touch_session("sess-a", current_time=t0, message_increment=1, prefix_content="System preamble")
    assert snap.state == SessionLifecycleState.ACTIVE
    assert snap.message_count == 1
    assert snap.inactivity_seconds == 0.0

    # Fast-forward 24 hours (still active)
    t1 = t0 + 24.0 * 3600.0
    assert mgr.evaluate_session_state("sess-a", current_time=t1) == SessionLifecycleState.ACTIVE

    # Fast-forward 50 hours (idle warning)
    t2 = t0 + 50.0 * 3600.0
    assert mgr.evaluate_session_state("sess-a", current_time=t2) == SessionLifecycleState.IDLE_STABLE

    # New interaction refreshes sliding window back to ACTIVE
    snap_refreshed = mgr.touch_session("sess-a", current_time=t2, message_increment=2)
    assert snap_refreshed.state == SessionLifecycleState.ACTIVE
    assert snap_refreshed.message_count == 3
    assert mgr.evaluate_session_state("sess-a", current_time=t2) == SessionLifecycleState.ACTIVE


def test_inactivity_sliding_window_expiration_and_sweep() -> None:
    """Verifies timeout expiration, automatic sweeping, and crystallization upon archival."""
    config = InactivityWindowConfig(
        inactivity_timeout_seconds=72.0 * 3600.0,
        idle_warning_threshold_seconds=48.0 * 3600.0,
        auto_crystallize_on_archive=True,
    )
    mgr = InactivitySlidingWindowSessionManager(config=config)

    t0 = 10000.0
    mgr.touch_session("sess-exp", current_time=t0)

    # 73 hours later (expired)
    t_expired = t0 + 73.0 * 3600.0
    state = mgr.evaluate_session_state("sess-exp", current_time=t_expired)
    assert state == SessionLifecycleState.EXPIRED_PENDING_ARCHIVE

    messages_store = {
        "sess-exp": [
            {"role": "user", "content": "My preference is to write clean async Python code."},
            {"role": "assistant", "content": "Understood. Decision: we adopt pytest and asyncio."},
            {"role": "assistant", "content": "Note: sqlite will be used as local memory storage."},
        ]
    }

    archived_list = mgr.sweep_and_archive_expired_sessions(
        session_messages_provider=messages_store, current_time=t_expired
    )
    assert len(archived_list) == 1
    archived = archived_list[0]
    assert archived.state == SessionLifecycleState.ARCHIVED
    assert archived.crystallized_memory is not None
    assert len(archived.crystallized_memory.user_preferences) == 1
    assert len(archived.crystallized_memory.key_decisions) == 1
    assert len(archived.crystallized_memory.extracted_facts) == 1
    assert "Archived session sess-exp after 73.0h" in archived.crystallized_memory.summary_headline


def test_manual_archive_and_crystallization() -> None:
    """Verifies immediate manual session archival and snapshot state."""
    mgr = InactivitySlidingWindowSessionManager()
    t0 = 20000.0
    mgr.touch_session("sess-manual", current_time=t0)

    history = [
        {"role": "user", "content": "用户偏好: 保持代码简洁并在前端使用 TailwindCSS"},
        {"role": "assistant", "content": "核心架构结论: 保持 harness 独立闭源并避免反向依赖"},
    ]

    snap = mgr.manual_archive_session("sess-manual", messages=history, current_time=t0 + 3600.0)
    assert snap.state == SessionLifecycleState.ARCHIVED
    assert snap.crystallized_memory is not None
    assert len(snap.crystallized_memory.user_preferences) == 1
    assert len(snap.crystallized_memory.key_decisions) == 1

    # Direct test of SessionMemoryCrystallizer
    c_mem = SessionMemoryCrystallizer.crystallize(
        session_id="sess-direct",
        messages=history,
        inactivity_duration_seconds=3600.0,
        current_time=t0 + 3600.0,
    )
    assert c_mem.session_id == "sess-direct"
    assert len(c_mem.user_preferences) == 1
    assert len(c_mem.key_decisions) == 1


def test_thread_safe_concurrent_touch() -> None:
    """Verifies that concurrent touch operations are thread-safe and avoid race conditions."""
    mgr = InactivitySlidingWindowSessionManager()
    session_id = "sess-concurrency"
    concurrency_count = 50

    def worker(i: int) -> None:
        mgr.touch_session(session_id, current_time=1000.0 + float(i), message_increment=1)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(worker, i) for i in range(concurrency_count)]
        for f in concurrent.futures.as_completed(futures):
            f.result()

    snap = mgr.get_session_snapshot(session_id)
    assert snap is not None
    assert snap.message_count == concurrency_count
