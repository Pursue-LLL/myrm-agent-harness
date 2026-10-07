"""Unit tests for PreFlightPrefixIntegrityBarrier and immutable payload freezing.

Validates pre-flight freeze, golden baseline lock, active drift blocking, and exemptions,
benchmarked against DeepSeek Harness 5-step cache protection and request freeze architecture.
"""

from concurrent.futures import ThreadPoolExecutor

import pytest

from myrm_agent_harness.runtime.context.prefix_integrity_barrier_types import (
    BarrierInterceptionMode,
    PrefixDriftKind,
    PrefixIntegrityViolationError,
)
from myrm_agent_harness.runtime.context.prefix_integrity_freeze_barrier import (
    PreFlightPrefixIntegrityBarrier,
)


def _sample_tools() -> list[dict[str, str]]:
    """Helper providing standard tool schemas for tests."""
    return [
        {"name": "read_file", "description": "Read file contents", "parameters": '{"path": "string"}'},
        {"name": "write_file", "description": "Write file contents", "parameters": '{"path": "string", "content": "string"}'},
    ]


def test_freeze_payload_and_first_turn_baseline_establishment() -> None:
    """Verifies outgoing request is immutably frozen and golden baseline is locked on turn 1."""
    barrier = PreFlightPrefixIntegrityBarrier(mode=BarrierInterceptionMode.STRICT_ASSERTION)
    session_id = "sess-alpha-001"

    payload1 = barrier.freeze_payload(
        session_id=session_id,
        system_prompt="You are a senior software architect.",
        tools=_sample_tools(),
        messages_count=1,
        model_name="deepseek-chat",
    )

    assert payload1.session_id == session_id
    assert len(payload1.system_prompt_sha256) == 64
    assert len(payload1.tools_fingerprint_sha256) == 64
    assert len(payload1.tools) == 2

    # Verify pre-flight inspection establishes baseline
    res = barrier.inspect_and_assert_pre_flight(payload1)
    assert res.is_valid is True
    assert res.is_baseline_established is True
    assert res.drifts == ()

    baseline = barrier.get_baseline(session_id)
    assert baseline is not None
    assert baseline.system_prompt_sha256 == payload1.system_prompt_sha256
    assert baseline.tools_fingerprint_sha256 == payload1.tools_fingerprint_sha256


def test_second_turn_clean_prefix_passes_inspection() -> None:
    """Verifies that subsequent turn with preserved prefix passes with zero barriers."""
    barrier = PreFlightPrefixIntegrityBarrier(mode=BarrierInterceptionMode.STRICT_ASSERTION)
    session_id = "sess-alpha-002"

    payload1 = barrier.freeze_payload(
        session_id=session_id,
        system_prompt="You are a senior software architect.",
        tools=_sample_tools(),
        messages_count=1,
        model_name="deepseek-chat",
    )
    barrier.inspect_and_assert_pre_flight(payload1)

    # Turn 2: message count increased, but system prompt & tools are 100% identical
    payload2 = barrier.freeze_payload(
        session_id=session_id,
        system_prompt="You are a senior software architect.",
        tools=_sample_tools(),
        messages_count=3,
        model_name="deepseek-chat",
    )
    res2 = barrier.inspect_and_assert_pre_flight(payload2)
    assert res2.is_valid is True
    assert res2.is_baseline_established is False
    assert len(res2.drifts) == 0


def test_strict_assertion_blocks_system_prompt_mutation() -> None:
    """Verifies that accidental system prompt drift is hard-blocked before network call."""
    barrier = PreFlightPrefixIntegrityBarrier(mode=BarrierInterceptionMode.STRICT_ASSERTION)
    session_id = "sess-alpha-003"

    payload1 = barrier.freeze_payload(
        session_id=session_id,
        system_prompt="Stable system baseline prompt",
        tools=_sample_tools(),
        messages_count=1,
        model_name="deepseek-chat",
    )
    barrier.inspect_and_assert_pre_flight(payload1)

    # Turn 2: middleware inadvertently injects a dynamic timestamp into system prompt!
    drifted_payload = barrier.freeze_payload(
        session_id=session_id,
        system_prompt="Stable system baseline prompt (Time: 2026-10-07 12:00:00)",
        tools=_sample_tools(),
        messages_count=3,
        model_name="deepseek-chat",
    )

    with pytest.raises(PrefixIntegrityViolationError) as exc_info:
        barrier.inspect_and_assert_pre_flight(drifted_payload)

    err = exc_info.value
    assert err.drift_kind == PrefixDriftKind.SYSTEM_PROMPT_MUTATION
    assert "System prompt SHA-256 changed" in err.details


def test_tool_schema_or_order_drift_detection() -> None:
    """Verifies tool reordering or schema modification is proactively blocked."""
    barrier = PreFlightPrefixIntegrityBarrier(mode=BarrierInterceptionMode.STRICT_ASSERTION)
    session_id = "sess-alpha-004"

    payload1 = barrier.freeze_payload(
        session_id=session_id,
        system_prompt="Stable prompt",
        tools=_sample_tools(),
        messages_count=1,
        model_name="deepseek-chat",
    )
    barrier.inspect_and_assert_pre_flight(payload1)

    # Invert tool ordering: write_file first, read_file second
    inverted_tools = list(reversed(_sample_tools()))
    inverted_payload = barrier.freeze_payload(
        session_id=session_id,
        system_prompt="Stable prompt",
        tools=inverted_tools,
        messages_count=2,
        model_name="deepseek-chat",
    )

    with pytest.raises(PrefixIntegrityViolationError) as exc_info:
        barrier.inspect_and_assert_pre_flight(inverted_payload)

    assert exc_info.value.drift_kind == PrefixDriftKind.TOOL_SCHEMA_MUTATION


def test_authorized_exemption_and_warn_only_mode() -> None:
    """Verifies authorized exemption resets baseline and WARN_AUDIT_ONLY does not raise."""
    barrier = PreFlightPrefixIntegrityBarrier(mode=BarrierInterceptionMode.STRICT_ASSERTION)
    session_id = "sess-alpha-005"

    payload1 = barrier.freeze_payload(
        session_id=session_id,
        system_prompt="Initial prompt v1",
        tools=_sample_tools(),
        messages_count=1,
        model_name="deepseek-chat",
    )
    barrier.inspect_and_assert_pre_flight(payload1)

    # Grant exemption for model switch
    barrier.grant_authorized_drift(session_id=session_id, reason="Intentional upgrade to v2")
    payload2 = barrier.freeze_payload(
        session_id=session_id,
        system_prompt="Upgraded prompt v2",
        tools=_sample_tools(),
        messages_count=2,
        model_name="deepseek-coder",
    )
    res_exempt = barrier.inspect_and_assert_pre_flight(payload2)
    assert res_exempt.is_valid is True
    assert res_exempt.exemption_granted is True

    # Test WARN_AUDIT_ONLY mode tolerates drift without throwing
    barrier.set_interception_mode(BarrierInterceptionMode.WARN_AUDIT_ONLY)
    payload3 = barrier.freeze_payload(
        session_id=session_id,
        system_prompt="Tolerated drift v3",
        tools=_sample_tools(),
        messages_count=3,
        model_name="deepseek-coder",
    )
    res_warn = barrier.inspect_and_assert_pre_flight(payload3)
    assert res_warn.is_valid is False
    assert PrefixDriftKind.SYSTEM_PROMPT_MUTATION in res_warn.drifts


def test_multithreaded_concurrency() -> None:
    """Verifies thread-safety under concurrent freezes and validations across 10 sessions."""
    barrier = PreFlightPrefixIntegrityBarrier(mode=BarrierInterceptionMode.STRICT_ASSERTION)

    def _worker(worker_id: int) -> bool:
        s_id = f"concurrent-sess-{worker_id}"
        p1 = barrier.freeze_payload(
            session_id=s_id,
            system_prompt=f"System prompt for {worker_id}",
            tools=_sample_tools(),
            messages_count=1,
            model_name="deepseek-chat",
        )
        r1 = barrier.inspect_and_assert_pre_flight(p1)

        p2 = barrier.freeze_payload(
            session_id=s_id,
            system_prompt=f"System prompt for {worker_id}",
            tools=_sample_tools(),
            messages_count=2,
            model_name="deepseek-chat",
        )
        r2 = barrier.inspect_and_assert_pre_flight(p2)
        return r1.is_valid and r2.is_valid

    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(_worker, range(10)))

    assert all(results)
    assert len(barrier.get_audit_history()) == 20
