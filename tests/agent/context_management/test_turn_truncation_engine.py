"""单元测试：执行回合原子裁切、前缀缓存纯化与试错中间态防污染网关套件 (Item 205).

[INPUT]
- TurnStateTruncationEngine
- CanonicalTurnCommit
- IntermediateTrialKind
- PrefixCacheStabilityReport
- TrialStepRecord
- TruncationPolicy
- TurnExecutionState

[OUTPUT]
- 验证回合内试错报错原子剥离、仅保留规范交互凭证
- 验证折叠自纠偏失败日志为单行紧凑状态证据
- 验证脏状态透传策略
- 验证多回合会话前缀稳定性诊断与缓存命中率预测
"""

from __future__ import annotations

from myrm_agent_harness.agent.context_management.turn_truncation import (
    CanonicalTurnCommit,
    IntermediateTrialKind,
    PrefixCacheStabilityReport,
    TrialStepRecord,
    TruncationPolicy,
    TurnExecutionState,
    TurnStateTruncationEngine,
)


def test_prune_all_failures_keep_canonical() -> None:
    """验证严格原子裁切：剥离单回合内的失败工具调用与报错堆栈，仅提交权威有效凭证。"""
    engine = TurnStateTruncationEngine()
    turn_id = "turn_101"

    engine.begin_turn(turn_id)
    engine.record_intermediate_trial(
        turn_id=turn_id,
        kind=IntermediateTrialKind.SYNTAX_ERROR_RETRY,
        tool_name="python_repl",
        error_message="SyntaxError: invalid syntax",
        raw_char_count=300,
    )
    engine.record_intermediate_trial(
        turn_id=turn_id,
        kind=IntermediateTrialKind.FAILED_TOOL_CALL,
        tool_name="bash",
        error_message="Command failed with exit code 1",
        raw_char_count=400,
    )

    in_flight_messages: list[dict[str, object]] = [
        {"role": "user", "content": "请计算总销售额"},
        {
            "role": "assistant",
            "content": "执行脚本进行统计",
            "tool_calls": [{"name": "python_repl", "args": {"code": "bad_code("}}],
        },
        {
            "role": "tool",
            "content": "Traceback (most recent call last):\n  File 'test.py': SyntaxError: invalid syntax",
            "is_error": True,
        },
        {
            "role": "assistant",
            "content": "纠正语法并重新计算",
            "tool_calls": [{"name": "python_repl", "args": {"code": "sum([10, 20])"}}],
        },
        {
            "role": "tool",
            "content": "Result: 30",
            "is_error": False,
        },
        {
            "role": "assistant",
            "content": "总销售额计算完毕，合计为 30 万元。",
        },
    ]

    commit: CanonicalTurnCommit = engine.canonical_commit(
        turn_id=turn_id,
        in_flight_messages=in_flight_messages,
        policy=TruncationPolicy.PRUNE_ALL_FAILURES_KEEP_CANONICAL,
    )

    assert commit.state == TurnExecutionState.TRUNCATED_AND_COMMITTED
    assert commit.prefix_cache_safe is True
    assert commit.pruned_trials_count >= 1
    assert commit.reclaimed_tokens_estimate > 0

    # 验证提交的消息中已不包含报错堆栈
    tool_contents = [
        str(m.get("content", ""))
        for m in commit.canonical_messages
        if m.get("role") in ("tool", "toolResult")
    ]
    for c in tool_contents:
        assert "SyntaxError" not in c
        assert "Traceback" not in c
    assert any("Result: 30" in c for c in tool_contents)


def test_fold_failures_to_one_line() -> None:
    """验证折叠策略：将多次失败日志折叠为单行结构化 Self-Correction Proof。"""
    engine = TurnStateTruncationEngine()
    turn_id = "turn_102"

    engine.begin_turn(turn_id)
    engine.record_intermediate_trial(
        turn_id=turn_id,
        kind=IntermediateTrialKind.PROBE,
        tool_name="cat",
        error_message="Error: Cannot find module",
        raw_char_count=500,
    )

    in_flight_messages: list[dict[str, object]] = [
        {"role": "user", "content": "检查配置"},
        {
            "role": "tool",
            "content": "Error: Cannot find module 'settings'",
            "is_error": True,
        },
        {"role": "assistant", "content": "已切换到正确路径并完成配置确认。"},
    ]

    commit = engine.canonical_commit(
        turn_id=turn_id,
        in_flight_messages=in_flight_messages,
        policy=TruncationPolicy.FOLD_FAILURES_TO_ONE_LINE,
    )

    assert commit.state == TurnExecutionState.TRUNCATED_AND_COMMITTED
    assert commit.prefix_cache_safe is True

    # 验证插入了单行折叠摘要，原巨幅报错被剔除
    contents = [str(m.get("content", "")) for m in commit.canonical_messages]
    assert any("[Self-Correction Proof]" in c for c in contents)
    assert not any("Error: Cannot find module 'settings'" in c for c in contents)


def test_passthrough_dirty_policy() -> None:
    """验证透传模式：保留全部脏状态与报错，标记 prefix_cache_safe=False。"""
    engine = TurnStateTruncationEngine()
    turn_id = "turn_103"

    in_flight_messages: list[dict[str, object]] = [
        {"role": "user", "content": "测试指令"},
        {"role": "tool", "content": "SyntaxError: fail", "is_error": True},
    ]

    commit = engine.canonical_commit(
        turn_id=turn_id,
        in_flight_messages=in_flight_messages,
        policy=TruncationPolicy.PASSTHROUGH_DIRTY,
    )

    assert commit.state == TurnExecutionState.COMMITTED
    assert commit.prefix_cache_safe is False
    assert len(commit.canonical_messages) == 2


def test_audit_prefix_cache_stability_report() -> None:
    """验证多回合会话前缀稳定性诊断、Hash 摘要生成与缓存命中率预测。"""
    engine = TurnStateTruncationEngine()

    commits: list[CanonicalTurnCommit] = [
        CanonicalTurnCommit(
            turn_id=f"t_{i}",
            canonical_messages=[{"role": "user", "content": f"msg {i}"}],
            pruned_trials_count=2,
            reclaimed_tokens_estimate=100,
            prefix_cache_safe=True,
            state=TurnExecutionState.TRUNCATED_AND_COMMITTED,
        )
        for i in range(5)
    ]

    report: PrefixCacheStabilityReport = engine.audit_prefix_cache_stability(commits)
    assert report.total_turns == 5
    assert report.canonical_turns == 5
    assert report.is_prefix_stable is True
    assert report.cache_hit_likelihood_pct >= 95.0
    assert report.total_reclaimed_tokens == 500
    assert len(report.prefix_digest) == 64

    # 验证当混入未清洗回合时，命中率投影合理下降
    dirty_commits = list(commits)
    dirty_commits.append(
        CanonicalTurnCommit(
            turn_id="t_dirty",
            canonical_messages=[{"role": "user", "content": "dirty"}],
            pruned_trials_count=0,
            reclaimed_tokens_estimate=0,
            prefix_cache_safe=False,
            state=TurnExecutionState.COMMITTED,
        )
    )
    dirty_report = engine.audit_prefix_cache_stability(dirty_commits)
    assert dirty_report.cache_hit_likelihood_pct < report.cache_hit_likelihood_pct
