"""Unit tests for DualLayerProfileMemoryBudgetAndGarbagePurgeGuard.

[INPUT]
- profile_notes: MemoryIntakeGarbageFilter, CapacityWatermarkGovernor, types

[OUTPUT]
- Pytest test cases verifying intake filter precision and capacity watermark thresholds

[POS]
Harness toolkit memory tests enforcing Hermes-grade noise rejection and strict budget limits.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.memory.profile_notes import (
    DEFAULT_MEMORY_MAX_CHARS,
    DEFAULT_USER_MAX_CHARS,
    CapacityWatermarkGovernor,
    GarbageCategory,
    MemoryIntakeGarbageFilter,
    MemoryLayerType,
    WatermarkLevel,
)


@pytest.fixture
def garbage_filter() -> MemoryIntakeGarbageFilter:
    return MemoryIntakeGarbageFilter()


@pytest.fixture
def watermark_governor() -> CapacityWatermarkGovernor:
    return CapacityWatermarkGovernor()


def test_reject_ephemeral_task_progress(garbage_filter: MemoryIntakeGarbageFilter) -> None:
    progress_samples = [
        "Phase 3 completed successfully",
        "Step 4 finished and passed all tests",
        "第二阶段已完成全部工作",
        "子任务已跑通，准备提交",
        "All tests passed in 12.5s",
    ]
    for sample in progress_samples:
        decision = garbage_filter.evaluate_intake(sample)
        assert not decision.accepted, f"Failed to reject progress sample: {sample}"
        assert decision.garbage_category == GarbageCategory.TASK_PROGRESS
        assert decision.rejected_reason is not None


def test_reject_ephemeral_numbers_and_references(
    garbage_filter: MemoryIntakeGarbageFilter,
) -> None:
    ephemeral_samples = [
        "Please review PR #882 for the memory fixes",
        "See issue #1234 regarding the timeout problem",
        "Fixed in commit a1b2c3d4e5f67890",
        "Tracking under task-4046",
    ]
    for sample in ephemeral_samples:
        decision = garbage_filter.evaluate_intake(sample)
        assert not decision.accepted, f"Failed to reject ephemeral reference: {sample}"
        assert decision.garbage_category == GarbageCategory.EPHEMERAL_NUMBER


def test_reject_transient_error_traceback(
    garbage_filter: MemoryIntakeGarbageFilter,
) -> None:
    error_samples = [
        "Traceback (most recent call last):\n  File 'test.py', line 12, in <module>",
        "Exception: Database connection lost",
        "Process exited with exit code 137",
        "Worker was oom killed by kernel",
    ]
    for sample in error_samples:
        decision = garbage_filter.evaluate_intake(sample)
        assert not decision.accepted, f"Failed to reject error sample: {sample}"
        assert decision.garbage_category == GarbageCategory.TRANSIENT_ERROR


def test_reject_transient_temporal_statements(
    garbage_filter: MemoryIntakeGarbageFilter,
) -> None:
    temporal_samples = [
        "刚才测试了一下，发现服务有些卡顿",
        "刚刚提交了代码，等待 CI 跑完",
        "Just now, we noticed the server latency spiked",
    ]
    for sample in temporal_samples:
        decision = garbage_filter.evaluate_intake(sample)
        assert not decision.accepted, f"Failed to reject temporal sample: {sample}"
        assert decision.garbage_category == GarbageCategory.TRANSIENT_TEMPORAL


def test_accept_user_long_term_preferences(
    garbage_filter: MemoryIntakeGarbageFilter,
) -> None:
    user_samples = [
        "用户代码风格偏好使用 Python PEP8 规范，严禁使用 Any 类型",
        "My preference is to always use concise commit messages in English",
        "我的名字是 Bob，母语为中文，习惯使用 VSCode",
    ]
    for sample in user_samples:
        decision = garbage_filter.evaluate_intake(sample)
        assert decision.accepted, f"Incorrectly rejected valid user preference: {sample}"
        assert decision.target_layer == MemoryLayerType.USER
        assert decision.rejected_reason is None


def test_accept_agent_working_notes_and_architecture(
    garbage_filter: MemoryIntakeGarbageFilter,
) -> None:
    agent_samples = [
        "本项目架构规范要求框架与业务分层，禁止反向依赖",
        "Architecture guideline: keep individual files under 400 lines",
        "Best practice: always use fractal headers [INPUT]/[OUTPUT]/[POS]",
    ]
    for sample in agent_samples:
        decision = garbage_filter.evaluate_intake(sample)
        assert decision.accepted, f"Incorrectly rejected valid note: {sample}"
        assert decision.target_layer == MemoryLayerType.MEMORY
        assert decision.rejected_reason is None


def test_empty_content_rejection(garbage_filter: MemoryIntakeGarbageFilter) -> None:
    decision = garbage_filter.evaluate_intake("   ")
    assert not decision.accepted
    assert decision.target_layer is None
    assert "Empty content" in (decision.rejected_reason or "")


def test_capacity_watermark_tiers(
    watermark_governor: CapacityWatermarkGovernor,
) -> None:
    # 1. Safe Level (<= 70%)
    safe_text = "A" * int(DEFAULT_USER_MAX_CHARS * 0.5)
    status_safe = watermark_governor.check_watermark(MemoryLayerType.USER, safe_text)
    assert status_safe.level == WatermarkLevel.SAFE
    assert status_safe.warning_message is None
    allowed, _ = watermark_governor.can_ingest(MemoryLayerType.USER, safe_text, "")
    assert allowed

    # 2. Warning Level (70% - 90%)
    warning_text = "B" * int(DEFAULT_USER_MAX_CHARS * 0.75)
    status_warn = watermark_governor.check_watermark(MemoryLayerType.USER, warning_text)
    assert status_warn.level == WatermarkLevel.WARNING
    assert status_warn.warning_message is not None
    assert "Approaching warning threshold" in status_warn.warning_message
    allowed, _ = watermark_governor.can_ingest(MemoryLayerType.USER, warning_text, "")
    assert allowed

    # 3. Critical Level (90% - 100%)
    critical_text = "C" * int(DEFAULT_USER_MAX_CHARS * 0.95)
    status_crit = watermark_governor.check_watermark(MemoryLayerType.USER, critical_text)
    assert status_crit.level == WatermarkLevel.CRITICAL
    assert status_crit.warning_message is not None
    assert "Critical capacity reached" in status_crit.warning_message
    allowed, _ = watermark_governor.can_ingest(MemoryLayerType.USER, critical_text, "")
    assert allowed

    # 4. Overflow Level (> 100%)
    overflow_text = "D" * (DEFAULT_USER_MAX_CHARS + 50)
    status_over = watermark_governor.check_watermark(MemoryLayerType.USER, overflow_text)
    assert status_over.level == WatermarkLevel.OVERFLOW
    assert status_over.warning_message is not None
    assert "Capacity OVERFLOW" in status_over.warning_message
    allowed, status = watermark_governor.can_ingest(MemoryLayerType.USER, overflow_text, "")
    assert not allowed
    assert status.level == WatermarkLevel.OVERFLOW


def test_memory_layer_independent_limits(
    watermark_governor: CapacityWatermarkGovernor,
) -> None:
    assert watermark_governor.get_max_chars(MemoryLayerType.USER) == DEFAULT_USER_MAX_CHARS
    assert watermark_governor.get_max_chars(MemoryLayerType.MEMORY) == DEFAULT_MEMORY_MAX_CHARS
