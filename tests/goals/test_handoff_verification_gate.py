from __future__ import annotations

import pytest

from myrm_agent_harness.agent.goals.verification import (
    HandoffVerificationGate,
    HandoffVerificationSeverity,
)
from myrm_agent_harness.runtime.context.session_handoff_continuation_types import (
    HandoffTriggerReason,
    RejectedAlternativeRecord,
    StructuredHandoffMemo,
)


@pytest.fixture
def base_memo() -> StructuredHandoffMemo:
    return StructuredHandoffMemo(
        memo_id="memo-test-001",
        source_session_id="session-src-001",
        created_at="2026-10-07T12:00:00Z",
        trigger_reason=HandoffTriggerReason.CAPACITY_SATURATION,
        current_objective="完成高性能流式响应服务重构",
        completed_milestones=["设计数据模型", "编写单元测试框架"],
        active_hypotheses=["SSE 协议相比 WebSocket 更轻量"],
        rejected_alternatives=[
            RejectedAlternativeRecord(
                proposed_approach="使用全局锁同步并发请求",
                failure_reason="造成严重的锁竞争与吞吐量下降",
                prevent_retry=True,
            )
        ],
        critical_constraints=[
            "单文件代码行数严格不超过 400 行",
            "禁止使用 Any 类型",
        ],
        next_action_plan=["实现心跳保活中间件", "全量回归测试"],
        modified_files_and_artifacts=["src/stream.py"],
        external_state_anchors={"git_commit": "abcdef123"},
    )


def test_handoff_verification_passes_when_all_constraints_present(
    base_memo: StructuredHandoffMemo,
) -> None:
    gate = HandoffVerificationGate()
    user_constraints = [
        "单文件代码行数严格不超过 400 行",
        "禁止使用 Any 类型",
    ]
    disqualified = ["使用全局锁同步并发请求"]

    res = gate.verify_and_rectify(
        memo=base_memo,
        user_critical_constraints=user_constraints,
        disqualified_approaches=disqualified,
        auto_rectify=True,
    )

    assert res.passed is True
    assert res.fidelity_score == 1.0
    assert len(res.issues) == 0
    assert len(res.missing_constraints) == 0
    assert len(res.missing_negative_decisions) == 0
    assert res.is_rectified is False


def test_handoff_verification_detects_missing_constraints_and_rectifies(
    base_memo: StructuredHandoffMemo,
) -> None:
    gate = HandoffVerificationGate()
    user_constraints = [
        "单文件代码行数严格不超过 400 行",
        "禁止使用 Any 类型",
        "所有端点必须强制使用异步非阻塞 I/O",  # Omitted from base_memo
    ]
    disqualified = [
        "使用全局锁同步并发请求",
        "在主事件循环中执行 time.sleep",  # Omitted from base_memo
    ]

    res = gate.verify_and_rectify(
        memo=base_memo,
        user_critical_constraints=user_constraints,
        disqualified_approaches=disqualified,
        auto_rectify=True,
    )

    assert res.passed is False
    assert res.fidelity_score < 1.0
    assert "所有端点必须强制使用异步非阻塞 I/O" in res.missing_constraints
    assert "在主事件循环中执行 time.sleep" in res.missing_negative_decisions

    critical_issues = [i for i in res.issues if i.severity == HandoffVerificationSeverity.CRITICAL]
    assert len(critical_issues) == 1
    assert critical_issues[0].offending_item == "所有端点必须强制使用异步非阻塞 I/O"

    # Self-healing auto-rectification check
    assert res.is_rectified is True
    assert res.rectified_memo is not None
    assert "所有端点必须强制使用异步非阻塞 I/O" in res.rectified_memo.critical_constraints
    assert any(
        r.proposed_approach == "在主事件循环中执行 time.sleep"
        for r in res.rectified_memo.rejected_alternatives
    )
