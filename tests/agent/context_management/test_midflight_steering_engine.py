"""单元测试：长任务执行中实时追加指令、动态转向与非阻断式协同交互套件 (Item 207).

[INPUT]
- MidFlightSteeringCoordinator
- MidFlightDirective
- SteeringDirectiveStatus
- SteeringExecutionTelemetry
- SteeringInjectionEnvelope
- SteeringIntentKind

[OUTPUT]
- 验证多指令优先级排序入列与检查点原子出队
- 验证结构化提示词装配与队列非阻塞排空
- 验证代令生命周期跃迁、确认标记与遥测指标计算
- 验证会话清理与资源释放
"""

from __future__ import annotations

from myrm_agent_harness.agent.context_management.midflight_steering import (
    MidFlightDirective,
    MidFlightSteeringCoordinator,
    SteeringDirectiveStatus,
    SteeringExecutionTelemetry,
    SteeringInjectionEnvelope,
    SteeringIntentKind,
)


def test_enqueue_priority_ordering_and_drain() -> None:
    """验证按优先级由高到低出队，并验证状态由 QUEUED 原子跃迁为 INJECTED。"""
    coord = MidFlightSteeringCoordinator()
    sid = "session_steer_001"
    tid = "task_long_runner_01"

    # 先入列低优先级指令
    d1 = coord.enqueue_directive(
        session_id=sid,
        task_id=tid,
        content="顺便把图表加上暗黑模式支持",
        intent=SteeringIntentKind.APPEND_REQUIREMENT,
        priority=10,
    )
    # 再入列高优先级转向指令
    d2 = coord.enqueue_directive(
        session_id=sid,
        task_id=tid,
        content="忽略所有 mock 测试数据，仅统计生产库",
        intent=SteeringIntentKind.REORIENT,
        priority=50,
    )

    assert d1.status == SteeringDirectiveStatus.QUEUED
    assert d2.status == SteeringDirectiveStatus.QUEUED

    # 检查点出队
    envelope: SteeringInjectionEnvelope | None = coord.poll_and_inject_at_checkpoint(
        session_id=sid, checkpoint_step_index=3
    )

    assert envelope is not None
    assert len(envelope.injected_directives) == 2
    # 高优先级 d2 应该排在最前面
    assert envelope.injected_directives[0].directive_id == d2.directive_id
    assert envelope.injected_directives[1].directive_id == d1.directive_id

    # 验证状态与时间戳跃迁
    assert d1.status == SteeringDirectiveStatus.INJECTED
    assert d2.status == SteeringDirectiveStatus.INJECTED
    assert d1.injected_at is not None
    assert d2.injected_at is not None

    # 再次轮询应该无代令，返回 None
    second_poll = coord.poll_and_inject_at_checkpoint(session_id=sid, checkpoint_step_index=4)
    assert second_poll is None


def test_checkpoint_injection_envelope_composition() -> None:
    """验证装配生成标准的结构化提示词信封。"""
    coord = MidFlightSteeringCoordinator()
    sid = "session_steer_002"
    tid = "task_analysis"

    coord.enqueue_directive(
        session_id=sid,
        task_id=tid,
        content="表格按交易金额倒序排列",
        intent=SteeringIntentKind.APPEND_REQUIREMENT,
    )

    envelope = coord.poll_and_inject_at_checkpoint(session_id=sid, checkpoint_step_index=12)
    assert envelope is not None
    assert '<in-flight-steering checkpoint_step="12">' in envelope.composed_steering_prompt
    assert "- [Direct User Guidance (append_requirement)]: 表格按交易金额倒序排列" in envelope.composed_steering_prompt
    assert "</in-flight-steering>" in envelope.composed_steering_prompt


def test_mark_acknowledged_and_telemetry() -> None:
    """验证代令生命周期最终确认标记及延迟遥测计算。"""
    coord = MidFlightSteeringCoordinator()
    sid = "session_steer_003"
    tid = "task_etl"

    d = coord.enqueue_directive(
        session_id=sid,
        task_id=tid,
        content="限制并发线程数为 4",
        intent=SteeringIntentKind.REORIENT,
    )

    # 模拟检查点注入
    envelope = coord.poll_and_inject_at_checkpoint(session_id=sid, checkpoint_step_index=1)
    assert envelope is not None

    # 模拟执行引擎确认
    ok = coord.mark_acknowledged(session_id=sid, directive_id=d.directive_id)
    assert ok is True
    assert d.status == SteeringDirectiveStatus.ACKNOWLEDGED
    assert d.acknowledged_at is not None

    # 获取遥测大盘
    telemetry: SteeringExecutionTelemetry = coord.get_telemetry(session_id=sid)
    assert telemetry.total_received == 1
    assert telemetry.injected_count == 1
    assert telemetry.acknowledged_count == 1
    assert telemetry.pending_queue_length == 0
    assert telemetry.avg_latency_to_injection_ms >= 0.0

    as_dict = telemetry.to_dict()
    assert as_dict["total_received"] == 1
    assert as_dict["acknowledged_count"] == 1


def test_clear_session_cleanup() -> None:
    """验证会话清除后资源安全销毁。"""
    coord = MidFlightSteeringCoordinator()
    sid = "session_steer_clean"

    coord.enqueue_directive(
        session_id=sid,
        task_id="t1",
        content="test steer",
    )
    coord.clear_session(session_id=sid)

    telemetry = coord.get_telemetry(session_id=sid)
    assert telemetry.total_received == 0
    assert telemetry.pending_queue_length == 0
