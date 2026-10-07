"""单元测试：双阶段崩溃自愈会话自动提交与三维经验沉淀套件。

[INPUT]
- TwoPhaseSessionCommitEngine 及相关领域数据类型

[OUTPUT]
- 验证提交策略网关判定、Phase 1 毫秒级快照切割、Phase 2 异步三维经验提炼、崩溃自愈重试。

[POS]
- 位于 tests/agent/context_management/test_two_phase_session_commit_engine.py
"""

import json
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
import pytest

from myrm_agent_harness.agent.context_management.session_commit import (
    CommitJobStatus,
    CommitTriggerReason,
    SessionCommitPolicyConfig,
    TwoPhaseSessionCommitEngine,
)


def test_commit_policy_gateway_triggers() -> None:
    """验证提交策略网关在 Token 超限、轮次超限、空闲超时及显式结束时的触发。"""
    config = SessionCommitPolicyConfig(
        max_uncommitted_tokens=100_000,
        max_uncommitted_turns=30,
        idle_timeout_seconds=600.0,
    )
    engine = TwoPhaseSessionCommitEngine(config=config)

    # 1. 显式完成触发
    triggered, reason = engine.evaluate_commit_policy(0, 0, is_session_finished=True)
    assert triggered is True
    assert reason == CommitTriggerReason.EXPLICIT_FINISH

    # 2. Token 超限触发
    triggered, reason = engine.evaluate_commit_policy(uncommitted_tokens=120_000, uncommitted_turns=10)
    assert triggered is True
    assert reason == CommitTriggerReason.TOKEN_THRESHOLD

    # 3. 轮次超限触发
    triggered, reason = engine.evaluate_commit_policy(uncommitted_tokens=50_000, uncommitted_turns=35)
    assert triggered is True
    assert reason == CommitTriggerReason.TURNS_THRESHOLD

    # 4. 空闲超时触发
    triggered, reason = engine.evaluate_commit_policy(uncommitted_tokens=10_000, uncommitted_turns=5, idle_duration_seconds=700.0)
    assert triggered is True
    assert reason == CommitTriggerReason.IDLE_TIMEOUT

    # 5. 未达阈值不触发
    triggered, reason = engine.evaluate_commit_policy(uncommitted_tokens=20_000, uncommitted_turns=10, idle_duration_seconds=100.0)
    assert triggered is False
    assert reason is None


def test_phase1_snapshot_and_enqueue(tmp_path: Path) -> None:
    """验证 Phase 1 毫秒级划分活跃滑动窗口与历史归档落盘。"""
    config = SessionCommitPolicyConfig(live_window_turns=2)
    engine = TwoPhaseSessionCommitEngine(config=config)

    messages = [
        SystemMessage(content="System instruction base"),
        HumanMessage(content="Turn 1 user"),
        AIMessage(content="Turn 1 ai"),
        HumanMessage(content="Turn 2 user"),
        AIMessage(content="Turn 2 ai"),
        HumanMessage(content="Turn 3 user"),
        AIMessage(content="Turn 3 ai"),
        # 最新 2 轮（4 条消息受保护留在 Live 会话）
        HumanMessage(content="Turn 4 user live"),
        AIMessage(content="Turn 4 ai live"),
        HumanMessage(content="Turn 5 user live"),
        AIMessage(content="Turn 5 ai live"),
    ]

    result, live_msgs = engine.phase1_snapshot_and_enqueue(
        session_id="sess_101",
        messages=messages,
        trigger_reason=CommitTriggerReason.TOKEN_THRESHOLD,
        queue_dir=tmp_path,
    )

    assert result.status == "ready"
    assert result.live_messages_retained == 4
    assert result.archived_messages_count == 7
    assert len(live_msgs) == 4
    assert live_msgs[0].content == "Turn 4 user live"

    jobs_dir = tmp_path / "jobs"
    meta_files = list(jobs_dir.glob("*.meta.json"))
    assert len(meta_files) == 1

    meta_data = json.loads(meta_files[0].read_text(encoding="utf-8"))
    assert meta_data["status"] == CommitJobStatus.PENDING.value
    assert meta_data["session_id"] == "sess_101"
    assert meta_data["message_count"] == 7
    assert Path(meta_data["archived_payload_path"]).exists()


def test_phase2_tri_dimensional_distillation(tmp_path: Path) -> None:
    """验证 Phase 2 异步消费持久化队列并精准沉淀用户偏好、排障教训与新规。"""
    config = SessionCommitPolicyConfig(live_window_turns=1)
    engine = TwoPhaseSessionCommitEngine(config=config)

    messages = [
        SystemMessage(content="Base rules"),
        HumanMessage(content="I always prefer pytest with strict type hints for all test suites."),
        AIMessage(content="Understood, I will write typed pytest code."),
        ToolMessage(content="Error: FileNotFoundError when opening config file. Fixed by creating fallback default.", tool_call_id="call_1"),
        HumanMessage(content="We must ensure all database connections are closed properly, that is a project standard rule."),
        # live turn
        HumanMessage(content="Continue next turn"),
        AIMessage(content="Sure"),
    ]

    snap_res, _ = engine.phase1_snapshot_and_enqueue(
        session_id="sess_202",
        messages=messages,
        trigger_reason=CommitTriggerReason.EXPLICIT_FINISH,
        queue_dir=tmp_path,
    )
    assert snap_res.status == "ready"

    # 执行 Phase 2 异步提炼
    distilled_results = engine.phase2_execute_distillation(queue_dir=tmp_path)
    assert len(distilled_results) == 1

    distilled = distilled_results[0]
    assert distilled.session_id == "sess_202"

    # 1. 验证用户偏好提取
    assert len(distilled.preferences) >= 1
    pref = distilled.preferences[0]
    assert pref.category == "coding_style"
    assert "prefer pytest" in pref.preference_text

    # 2. 验证踩坑排障经验提取
    assert len(distilled.learnings) >= 1
    learning = distilled.learnings[0]
    assert "FileNotFoundError" in learning.problem_encountered

    # 3. 验证项目规范演进提取
    assert len(distilled.guidelines) >= 1
    assert any("database connections" in g.rule_statement for g in distilled.guidelines)

    # 验证任务状态更新为 COMPLETED
    jobs_dir = tmp_path / "jobs"
    meta_files = list(jobs_dir.glob("*.meta.json"))
    meta_data = json.loads(meta_files[0].read_text(encoding="utf-8"))
    assert meta_data["status"] == CommitJobStatus.COMPLETED.value


def test_crash_recovery_and_replay(tmp_path: Path) -> None:
    """验证进程异常重启中断后，自愈扫描将 IN_PROGRESS 作业安全重置回 PENDING 并重新消费。"""
    config = SessionCommitPolicyConfig(live_window_turns=1, max_retry_attempts=2)
    engine = TwoPhaseSessionCommitEngine(config=config)

    messages = [
        HumanMessage(content="I prefer concise markdown responses without verbose explanations."),
        AIMessage(content="Got it."),
        HumanMessage(content="Live user"),
        AIMessage(content="Live ai"),
    ]

    engine.phase1_snapshot_and_enqueue(
        session_id="sess_crash",
        messages=messages,
        trigger_reason=CommitTriggerReason.TURNS_THRESHOLD,
        queue_dir=tmp_path,
    )

    jobs_dir = tmp_path / "jobs"
    meta_file = list(jobs_dir.glob("*.meta.json"))[0]

    # 模拟在 Phase 2 执行过程中进程被 Kill，状态停留在 IN_PROGRESS
    raw_meta = json.loads(meta_file.read_text(encoding="utf-8"))
    raw_meta["status"] = CommitJobStatus.IN_PROGRESS.value
    meta_file.write_text(json.dumps(raw_meta, indent=2), encoding="utf-8")

    # 重启自愈恢复
    recovered = engine.recover_and_replay_crashed_jobs(queue_dir=tmp_path)
    assert recovered == 1

    updated_meta = json.loads(meta_file.read_text(encoding="utf-8"))
    assert updated_meta["status"] == CommitJobStatus.PENDING.value
    assert updated_meta["retry_count"] == 1

    # 重新消费成功
    distilled_list = engine.phase2_execute_distillation(queue_dir=tmp_path)
    assert len(distilled_list) == 1
    final_meta = json.loads(meta_file.read_text(encoding="utf-8"))
    assert final_meta["status"] == CommitJobStatus.COMPLETED.value
