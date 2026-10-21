"""Unit tests for Hierarchical Concurrency and Fan-Out Throttle Isolation Suite."""

from __future__ import annotations

import pytest

from myrm_agent_harness.runtime.concurrency_throttle import (
    BrakeSeverity,
    FanOutBrakingSentinel,
    FanOutLimitExceededError,
    HierarchicalQuotaMatrix,
    ResourceTier,
    TierQuotaConfig,
)


@pytest.mark.asyncio
async def test_multi_tier_quota_isolation() -> None:
    """Verify independent semaphore pools ensure heavy CPU tools cannot starve lightweight I/O tools."""
    configs = [
        TierQuotaConfig(ResourceTier.TOOL_SANDBOX_CPU, max_concurrency=2),
        TierQuotaConfig(ResourceTier.TOOL_IO, max_concurrency=5),
    ]
    matrix = HierarchicalQuotaMatrix(configs)

    # Acquire all available CPU sandbox leases (2 / 2)
    async with (
        matrix.acquire_lease(ResourceTier.TOOL_SANDBOX_CPU, session_id="s1"),
        matrix.acquire_lease(ResourceTier.TOOL_SANDBOX_CPU, session_id="s1"),
    ):
        # 3rd CPU lease attempt should timeout
        with pytest.raises(TimeoutError):
            async with matrix.acquire_lease(
                ResourceTier.TOOL_SANDBOX_CPU,
                session_id="s1",
                timeout_s=0.02,
            ):
                pass

        # CRITICAL ISOLATION: Tool I/O pool must remain fully available despite saturated CPU pool
        async with matrix.acquire_lease(ResourceTier.TOOL_IO, session_id="s2") as io_ticket:
            assert io_ticket.tier == ResourceTier.TOOL_IO
            assert matrix.get_tier_utilization(ResourceTier.TOOL_IO) == 0.2


@pytest.mark.asyncio
async def test_lease_automatic_release_on_exception() -> None:
    """Verify leases are 100% reliably released even when user code raises unhandled exceptions."""
    configs = [TierQuotaConfig(ResourceTier.AGENT_INSTANCE, max_concurrency=1)]
    matrix = HierarchicalQuotaMatrix(configs)

    with pytest.raises(ValueError, match="Simulated agent crash"):
        async with matrix.acquire_lease(ResourceTier.AGENT_INSTANCE, session_id="s_crash"):
            assert matrix.get_tier_utilization(ResourceTier.AGENT_INSTANCE) == 1.0
            raise ValueError("Simulated agent crash")

    # Invariant: Active count must drop to 0, allowing immediate re-acquisition
    assert matrix.get_tier_utilization(ResourceTier.AGENT_INSTANCE) == 0.0
    async with matrix.acquire_lease(ResourceTier.AGENT_INSTANCE, session_id="s_healthy") as ticket:
        assert ticket.session_id == "s_healthy"


@pytest.mark.asyncio
async def test_high_watermark_backpressure_detection() -> None:
    """Verify high-watermark backpressure threshold triggers accurately at configured capacity."""
    configs = [
        TierQuotaConfig(
            ResourceTier.LLM_PROVIDER,
            max_concurrency=5,
            high_watermark_ratio=0.8,  # 4 / 5 = 80%
        )
    ]
    matrix = HierarchicalQuotaMatrix(configs)

    assert matrix.is_high_watermark(ResourceTier.LLM_PROVIDER) is False

    # Acquire 4 leases (80% saturation)
    async with (
        matrix.acquire_lease(ResourceTier.LLM_PROVIDER),
        matrix.acquire_lease(ResourceTier.LLM_PROVIDER),
        matrix.acquire_lease(ResourceTier.LLM_PROVIDER),
        matrix.acquire_lease(ResourceTier.LLM_PROVIDER),
    ):
        assert matrix.get_tier_utilization(ResourceTier.LLM_PROVIDER) == 0.8
        assert matrix.is_high_watermark(ResourceTier.LLM_PROVIDER) is True


def test_fanout_tiered_braking_and_hard_limit_fuse() -> None:
    """Verify session fan-out sentinel enforces tiered progression: normal -> warning -> soft brake -> hard fuse."""
    sentinel = FanOutBrakingSentinel(soft_limit=3, brake_limit=5, hard_limit=7)
    session_id = "session_fanout_test"

    # Steps 1-2: Normal
    v1 = sentinel.record_derived_task(session_id)
    assert v1.severity == BrakeSeverity.NORMAL
    v2 = sentinel.record_derived_task(session_id)
    assert v2.severity == BrakeSeverity.NORMAL

    # Step 3: Warning threshold
    v3 = sentinel.record_derived_task(session_id)
    assert v3.severity == BrakeSeverity.WARNING
    assert v3.should_throttle is False

    # Step 5: Soft brake threshold
    sentinel.record_derived_task(session_id)  # Step 4
    v5 = sentinel.record_derived_task(session_id)  # Step 5
    assert v5.severity == BrakeSeverity.SOFT_BRAKE
    assert v5.should_throttle is True
    assert v5.should_fuse is False

    # Step 7: Hard safety budget breached -> raises exception
    sentinel.record_derived_task(session_id)  # Step 6
    with pytest.raises(FanOutLimitExceededError) as exc_info:
        sentinel.record_derived_task(session_id, raise_on_hard_limit=True)
    assert exc_info.value.count == 7


def test_fanout_turn_reset_and_markdown() -> None:
    """Verify session counters reset at conversational turn boundary and markdown cards render correctly."""
    sentinel = FanOutBrakingSentinel(soft_limit=2, brake_limit=4, hard_limit=6)
    sess = "sess_reset_test"

    sentinel.record_derived_task(sess)
    sentinel.record_derived_task(sess)
    assert sentinel.get_count(sess) == 2

    # Card rendering for Warning stage
    md_warn = sentinel.render_governance_markdown(sess)
    assert "### 🛡️ 扇出效应抑制与任务流治理看板" in md_warn
    assert "> [!NOTE]" in md_warn

    # Reset turn for next user message
    sentinel.reset_turn(sess)
    assert sentinel.get_count(sess) == 0

    # Clean state renders tip
    md_clean = sentinel.render_governance_markdown(sess)
    assert "> [!TIP]" in md_clean
