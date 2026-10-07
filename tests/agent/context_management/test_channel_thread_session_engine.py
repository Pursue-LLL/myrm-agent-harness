"""Unit tests for ChannelThreadSessionEngine."""

import pytest

from myrm_agent_harness.agent.context_management.channel_thread_session import (
    ChannelThreadSessionEngine,
    ThreadIsolationPolicy,
)


def test_channel_thread_topology_routing_and_canonical_keys() -> None:
    """Verify thread-aware channel routing accurately distinguishes thread vs main chat."""
    engine = ChannelThreadSessionEngine()

    # Message within a Feishu thread
    decision_thread = engine.resolve_thread_session(
        channel="Feishu",
        chat_id="oc_group_101",
        thread_id="th_issue_555",
    )
    assert decision_thread.is_thread_isolated is True
    assert decision_thread.target_session_key == "feishu:oc_group_101:thread:th_issue_555"
    assert decision_thread.reply_to_thread_id == "th_issue_555"
    assert decision_thread.branch_id.startswith("branch-")

    # Message in main group chat (no thread)
    decision_main = engine.resolve_thread_session(
        channel="Feishu",
        chat_id="oc_group_101",
        thread_id=None,
    )
    assert decision_main.is_thread_isolated is False
    assert decision_main.target_session_key == "feishu:oc_group_101:main"
    assert decision_main.reply_to_thread_id is None
    assert decision_main.branch_id == "main"


def test_multi_thread_context_isolation_zero_contamination() -> None:
    """Verify multiple concurrent threads in the same chat maintain 100% isolated contexts."""
    engine = ChannelThreadSessionEngine()
    channel = "slack"
    chat_id = "c_dev_team"

    thread_a_dec = engine.resolve_thread_session(channel, chat_id, thread_id="thread_payment_bug")
    thread_b_dec = engine.resolve_thread_session(channel, chat_id, thread_id="thread_frontend_i18n")

    # Thread A discusses payment timeout
    engine.append_message(
        session_key=thread_a_dec.target_session_key,
        role="user",
        content="Investigate payment timeout in stripe webhook.",
    )
    engine.append_message(
        session_key=thread_a_dec.target_session_key,
        role="assistant",
        content="Inspecting webhook log at /var/log/stripe.log.",
    )

    # Thread B discusses frontend internationalization
    engine.append_message(
        session_key=thread_b_dec.target_session_key,
        role="user",
        content="Add Arabic RTL support in header component.",
    )

    # Verify Thread A messages
    msgs_a = engine.get_messages(thread_a_dec.target_session_key)
    assert len(msgs_a) == 2
    assert "stripe webhook" in msgs_a[0]["content"]
    assert "Arabic RTL" not in msgs_a[0]["content"]

    # Verify Thread B messages
    msgs_b = engine.get_messages(thread_b_dec.target_session_key)
    assert len(msgs_b) == 1
    assert "Arabic RTL support" in msgs_b[0]["content"]
    assert "stripe webhook" not in msgs_b[0]["content"]

    # Main chat context remains completely untouched
    main_key = engine.build_canonical_session_key(channel, chat_id, None)
    assert len(engine.get_messages(main_key)) == 0


def test_thread_lifecycle_archive_and_summary_handoff() -> None:
    """Verify thread branch archival and concluding summary attachment."""
    engine = ChannelThreadSessionEngine(
        policy=ThreadIsolationPolicy(auto_summarize_on_archive=True)
    )
    channel = "feishu"
    chat_id = "oc_support_chat"

    # Spawn two threads
    th1 = engine.resolve_thread_session(channel, chat_id, thread_id="th_1")
    th2 = engine.resolve_thread_session(channel, chat_id, thread_id="th_2")

    active_before = engine.get_active_threads_in_chat(channel, chat_id)
    assert len(active_before) == 2

    # Archive thread 1 with concluding note
    archived = engine.archive_thread(
        session_key=th1.target_session_key,
        summary_text="Resolved: Database index added; latency dropped to 12ms.",
    )

    assert archived.is_active is False
    assert "Database index added" in (archived.summary or "")

    # Only thread 2 is active now
    active_after = engine.get_active_threads_in_chat(channel, chat_id)
    assert len(active_after) == 1
    assert active_after[0].thread_id == "th_2"


def test_independent_session_locks_zero_contention() -> None:
    """Verify each session key receives a distinct lock object to avoid contention."""
    engine = ChannelThreadSessionEngine()

    lock_main = engine.get_session_lock("feishu:chat_1:main")
    lock_th1 = engine.get_session_lock("feishu:chat_1:thread:th_1")
    lock_th2 = engine.get_session_lock("feishu:chat_1:thread:th_2")

    assert lock_main is not lock_th1
    assert lock_th1 is not lock_th2

    # Acquiring lock_th1 should not block acquiring lock_th2
    assert lock_th1.acquire(blocking=False) is True
    assert lock_th2.acquire(blocking=False) is True

    lock_th1.release()
    lock_th2.release()
