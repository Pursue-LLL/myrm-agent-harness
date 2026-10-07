"""Unit tests for Live Response Steering and Mid-Generation Correction Channel (Item 219).

[INPUT]
- LiveResponseSteeringEngine, LiveSteeringConfig, LiveSteeringInstruction, ToolSeamAnchor.
- Simulated in-flight tool seams and user intervention directives.

[OUTPUT]
- Deterministic verification of non-blocking queueing, supersede semantics,
- tool seam interception, tool call suppression, causal history reconciliation, and telemetry.

[POS]
- Verifies mid-flight steering without aborting long tasks or losing prior achievements.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.context_management.live_steering import (
    LiveResponseSteeringEngine,
    LiveSteerStatus,
    LiveSteeringConfig,
    LiveSteeringInstruction,
    SteerChannelMode,
    SteerSeverity,
    ToolSeamAnchor,
)


def test_submit_and_probe_live_steering() -> None:
    """Verifies directive submission, non-blocking probing, and input validation."""
    engine = LiveResponseSteeringEngine()

    assert engine.has_pending_steering("session_1", "turn_1") is False
    assert engine.peek_pending_steering("session_1", "turn_1") is None

    # Blank content should raise ValueError
    with pytest.raises(ValueError, match="cannot be empty"):
        engine.submit_live_steering(
            LiveSteeringInstruction(
                instruction_id="st_blank",
                session_id="session_1",
                turn_id="turn_1",
                content="   ",
            )
        )

    # Valid submission
    instruction = LiveSteeringInstruction(
        instruction_id="st_001",
        session_id="session_1",
        turn_id="turn_1",
        content="不要删除现有的测试脚本，保留并做增量兼容",
        severity=SteerSeverity.COURSE_CORRECTION,
    )
    submitted = engine.submit_live_steering(instruction)
    assert submitted.instruction_id == "st_001"
    assert submitted.status == LiveSteerStatus.QUEUED

    # Non-blocking probe should instantly report pending
    assert engine.has_pending_steering("session_1", "turn_1") is True
    peeked = engine.peek_pending_steering("session_1", "turn_1")
    assert peeked is not None
    assert peeked.instruction_id == "st_001"
    # Peek should NOT consume from queue
    assert engine.has_pending_steering("session_1", "turn_1") is True


def test_supersede_and_queue_eviction() -> None:
    """Verifies that consecutive directives supersede older queued ones under default config."""
    config = LiveSteeringConfig(max_pending_queue_size=2, allow_directive_supersede=True)
    engine = LiveResponseSteeringEngine(config=config)

    first = LiveSteeringInstruction(
        instruction_id="st_first",
        session_id="session_2",
        turn_id="turn_1",
        content="先搜索 tests 目录",
    )
    second = LiveSteeringInstruction(
        instruction_id="st_second",
        session_id="session_2",
        turn_id="turn_1",
        content="改换策略：直接运行 pytest，不要单独读文件",
    )

    engine.submit_live_steering(first)
    engine.submit_live_steering(second)

    # The first directive should be marked SUPERSEDED
    assert first.status == LiveSteerStatus.SUPERSEDED
    assert second.status == LiveSteerStatus.QUEUED

    # Queue should only retain the second directive
    peeked = engine.peek_pending_steering("session_2", "turn_1")
    assert peeked is not None
    assert peeked.instruction_id == "st_second"


def test_tool_seam_interception_and_suppression() -> None:
    """Verifies interception at execution seam and suppression of obsolete tool calls."""
    engine = LiveResponseSteeringEngine()

    directive = LiveSteeringInstruction(
        instruction_id="st_abort",
        session_id="sess_intervene",
        turn_id="turn_5",
        content="发现参数错误，立即停止写入数据库，改为记录本地审计日志",
        severity=SteerSeverity.ABORT_BRANCH,
        channel_mode=SteerChannelMode.TOOL_SEAM_INTERCEPT,
    )
    engine.submit_live_steering(directive)

    seam = ToolSeamAnchor(
        step_index=3,
        completed_tool_name="validate_token",
        pending_tool_count=2,
    )
    pending_tool_ids = ["tool_write_db_1", "tool_send_webhook_2"]

    result = engine.intercept_at_tool_seam(
        session_id="sess_intervene",
        turn_id="turn_5",
        seam_anchor=seam,
        pending_tool_ids=pending_tool_ids,
    )

    assert result is not None
    assert result.applied is True
    assert result.instruction_id == "st_abort"
    assert result.seam_step_index == 3
    # Abort branch severity suppresses all upcoming pending tool IDs
    assert result.suppressed_tool_ids == ["tool_write_db_1", "tool_send_webhook_2"]
    assert "Tool Suppression Notice" in result.injected_prompt_content
    assert "<in_flight_steering" in result.injected_prompt_content
    assert "立即停止写入数据库" in result.injected_prompt_content
    assert directive.status == LiveSteerStatus.APPLIED_AT_SEAM

    # Queue should now be empty for that turn
    assert engine.has_pending_steering("sess_intervene", "turn_5") is False


def test_advisory_severity_does_not_suppress_tools() -> None:
    """Verifies advisory severity provides course guidance without cancelling pending tools."""
    engine = LiveResponseSteeringEngine()

    directive = LiveSteeringInstruction(
        instruction_id="st_advisory",
        session_id="sess_adv",
        turn_id="turn_1",
        content="顺便把执行耗时也记录在响应中",
        severity=SteerSeverity.ADVISORY,
    )
    engine.submit_live_steering(directive)

    seam = ToolSeamAnchor(step_index=1, completed_tool_name="query_cache")
    result = engine.intercept_at_tool_seam(
        session_id="sess_adv",
        turn_id="turn_1",
        seam_anchor=seam,
        pending_tool_ids=["tool_calc_metrics"],
    )

    assert result is not None
    assert result.applied is True
    # Advisory directives do not suppress tools
    assert result.suppressed_tool_ids == []
    assert "Tool Suppression Notice" not in result.injected_prompt_content


def test_reconcile_causal_history() -> None:
    """Verifies causal interleaving of in-flight steers with recorded message history."""
    engine = LiveResponseSteeringEngine()

    directive = LiveSteeringInstruction(
        instruction_id="st_mid_1",
        session_id="sess_causal",
        turn_id="turn_10",
        content="不要格式化整个文件，仅针对第 20 到 30 行做补丁",
        severity=SteerSeverity.COURSE_CORRECTION,
    )
    engine.submit_live_steering(directive)

    # Intercept at step 1
    engine.intercept_at_tool_seam(
        session_id="sess_causal",
        turn_id="turn_10",
        seam_anchor=ToolSeamAnchor(step_index=1, completed_tool_name="read_file"),
    )

    raw_messages: list[dict[str, object]] = [
        {"role": "user", "content": "请修复格式问题"},
        {"role": "assistant", "content": "正在分析文件内容并准备全量重写..."},
        {"role": "assistant", "content": "已修正仅针对 20-30 行应用补丁。"},
    ]

    reconciled = engine.reconcile_causal_history(
        session_id="sess_causal",
        turn_id="turn_10",
        raw_messages=raw_messages,
    )

    assert reconciled.total_steers_applied == 1
    messages = reconciled.reconciled_messages
    # Message count should be 3 + 1 = 4
    assert len(messages) == 4
    # Steer message should be inserted right after step index 1
    assert messages[2]["role"] == "user"
    assert messages[2].get("is_mid_generation_steer") is True
    assert "仅针对第 20 到 30 行做补丁" in str(messages[2]["content"])


def test_telemetry_and_clear_session() -> None:
    """Verifies telemetry metrics and safe session teardown."""
    engine = LiveResponseSteeringEngine()

    directive = LiveSteeringInstruction(
        instruction_id="st_tel",
        session_id="sess_tel",
        turn_id="turn_1",
        content="测试遥测",
    )
    engine.submit_live_steering(directive)

    telemetry = engine.get_telemetry("sess_tel")
    assert telemetry["pending_steers"] == 1
    assert telemetry["applied_steers"] == 0

    engine.intercept_at_tool_seam(
        session_id="sess_tel",
        turn_id="turn_1",
        seam_anchor=ToolSeamAnchor(step_index=0),
    )

    telemetry_after = engine.get_telemetry("sess_tel")
    assert telemetry_after["pending_steers"] == 0
    assert telemetry_after["applied_steers"] == 1

    engine.clear_session("sess_tel")
    telemetry_cleared = engine.get_telemetry("sess_tel")
    assert telemetry_cleared["pending_steers"] == 0
    assert telemetry_cleared["applied_steers"] == 0
