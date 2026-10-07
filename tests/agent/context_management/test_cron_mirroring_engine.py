"""Unit tests for Continuable Cron Delivery and Session Mirroring Suite (Item 215).

[INPUT]
- ContinuableCronSessionMirrorEngine, ContinuableJobSpec, CronDeliveryRecord.
- Simulated multi-turn session conversations with alternating roles.

[OUTPUT]
- Deterministic verification of alternation-safe conversation mirroring,
- thread isolation, and follow-up query context retrieval.

[POS]
- Verifies that scheduled cron briefs become seamless, reply-ready conversational turns
- without triggering LLM role alternation violations or losing task context.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.context_management.cron_mirroring import (
    ContinuableCronSessionMirrorEngine,
    ContinuableJobSpec,
    CronDeliveryRecord,
    CronMirrorConfig,
    CronMirrorRoleMode,
)


def test_cron_job_registration_and_opt_out() -> None:
    """Verifies job spec registration and non-mirrored bypass when attach_to_session is disabled."""
    engine = ContinuableCronSessionMirrorEngine()
    job_spec = ContinuableJobSpec(
        job_id="daily_health_check",
        job_name="Daily Health Check",
        continuable=False,
        attach_to_session=False,
    )
    engine.register_job(job_spec)

    delivery = CronDeliveryRecord(
        delivery_id="deliv_001",
        job_id="daily_health_check",
        job_name="Daily Health Check",
        target_session_id="session_cron_001",
        content="System healthy. All 12 services reporting OK.",
    )

    initial_msgs: list[dict[str, object]] = [{"role": "user", "content": "Hello"}]
    updated_msgs, outcome = engine.mirror_delivery_into_session(delivery, initial_msgs)

    # Since attach_to_session is False, messages should remain untouched
    assert outcome.mirrored is False
    assert len(updated_msgs) == 1
    assert updated_msgs[0]["content"] == "Hello"


def test_alternation_safe_user_turn_mirroring_and_clamping() -> None:
    """Verifies that cron brief is injected as a labelled user turn and stays alternation-safe."""
    config = CronMirrorConfig(
        max_delivery_chars_in_context=50,
        default_role_mode=CronMirrorRoleMode.LABELLED_USER_TURN,
    )
    engine = ContinuableCronSessionMirrorEngine(config=config)

    job_spec = ContinuableJobSpec(
        job_id="morning_market_brief",
        job_name="Morning Market Brief",
        continuable=True,
        attach_to_session=True,
    )
    engine.register_job(job_spec)

    # 1. Existing conversation ends with assistant -> should inject as user
    history_ends_assistant: list[dict[str, object]] = [
        {"role": "user", "content": "Set up my morning cron."},
        {"role": "assistant", "content": "Cron job configured successfully."},
    ]

    delivery_long = CronDeliveryRecord(
        delivery_id="deliv_market_001",
        job_id="morning_market_brief",
        job_name="Morning Market Brief",
        target_session_id="session_cron_002",
        content="1. S&P500 up 0.8%. 2. Nasdaq flat. 3. Tech sector showing strong resistance against volatility.",
    )

    res_msgs, outcome = engine.mirror_delivery_into_session(delivery_long, history_ends_assistant)
    assert outcome.mirrored is True
    assert outcome.injected_role == "user"
    assert outcome.alternation_safe is True
    assert len(res_msgs) == 3

    # Clamping check: content clamped to ~50 chars + truncation notice
    last_msg = res_msgs[-1]
    assert "[Truncated" in str(last_msg["content"])
    assert "[Cron Delivery Brief: Morning Market Brief" in str(last_msg["content"])
    assert last_msg["metadata"]["continuable"] is True  # type: ignore[index]

    # 2. Existing conversation ends with user -> should inject as assistant to avoid consecutive user turns
    history_ends_user: list[dict[str, object]] = [
        {"role": "user", "content": "What is the status?"}
    ]
    res_msgs_2, outcome_2 = engine.mirror_delivery_into_session(delivery_long, history_ends_user)
    assert outcome_2.mirrored is True
    assert outcome_2.injected_role == "assistant"
    assert outcome_2.alternation_safe is True


def test_system_frame_mode_and_thread_isolation_routing() -> None:
    """Verifies SYSTEM_INSTRUCTION_FRAME mode and thread-specific follow-up context resolution."""
    engine = ContinuableCronSessionMirrorEngine(
        config=CronMirrorConfig(default_role_mode=CronMirrorRoleMode.SYSTEM_INSTRUCTION_FRAME)
    )

    delivery = CronDeliveryRecord(
        delivery_id="deliv_thread_99",
        job_id="secops_sweep",
        job_name="SecOps Sweep",
        target_session_id="session_cron_003",
        content="Found 2 high-severity dependency alerts in requirements.txt.",
        thread_id="slack_thread_12345",
    )

    updated_msgs, outcome = engine.mirror_delivery_into_session(delivery, [])
    assert outcome.mirrored is True
    assert outcome.injected_role == "system"
    assert outcome.thread_id == "slack_thread_12345"

    # Follow-up resolution via thread_id
    resolved = engine.resolve_follow_up_context(
        session_id="session_cron_003",
        query_text="Fix the second vulnerability.",
        thread_id="slack_thread_12345",
    )
    assert resolved is not None
    assert resolved.delivery_id == "deliv_thread_99"
    assert "Found 2 high-severity dependency alerts" in resolved.content

    # Follow-up resolution without thread_id (falling back to latest delivery in session)
    resolved_fallback = engine.resolve_follow_up_context(session_id="session_cron_003")
    assert resolved_fallback is not None
    assert resolved_fallback.delivery_id == "deliv_thread_99"

    # Clear session
    engine.clear_session("session_cron_003")
    assert engine.resolve_follow_up_context("session_cron_003") is None
