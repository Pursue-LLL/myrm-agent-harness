"""内外双层循环实时代令引导、键盘意图分流与排队队列套件单元测试。

[INPUT]
- DualLoopSessionQueueLedger, InnerLoopSteeringInterceptor, KeyStrokeIntent, LoopSteeringKind, SteeringDirectiveStatus, DualLoopQueueSnapshot

[OUTPUT]
- 自动化验证 Enter 中途改向分流、Alt+Enter 排队入列、Alt+↑ 弹性取回编辑、内层循环预推理代令原子装配与外层顺次执行

[POS]
- 位于 tests/agent/context_management/test_dual_loop_steering_engine.py
"""

from myrm_agent_harness.agent.context_management.dual_loop_steering import (
    DualLoopQueueSnapshot,
    DualLoopSessionQueueLedger,
    InnerLoopSteeringInterceptor,
    KeyStrokeIntent,
    LoopSteeringKind,
    SteeringDirective,
    SteeringDirectiveStatus,
)


def test_keystroke_intent_dispatch_and_queue_segregation() -> None:
    """测试极简键盘手势分流：Enter 进入内层实时改向，Alt+Enter 进入外层排队。"""
    ledger = DualLoopSessionQueueLedger()
    sid = "session_dual_01"

    # 1. 模拟长任务执行中，用户直接按 Enter 追加中途改向指令
    steer_dir = ledger.dispatch_keystroke_intent(
        session_id=sid,
        prompt_text="不要用递归算法，请改用迭代循环",
        intent=KeyStrokeIntent.ENTER_LIVE_STEER,
    )
    assert steer_dir is not None
    assert steer_dir.kind == LoopSteeringKind.INNER_LOOP_STEER
    assert steer_dir.status == SteeringDirectiveStatus.PENDING
    assert steer_dir.prompt_text == "不要用递归算法，请改用迭代循环"

    # 2. 模拟用户按 Alt+Enter 排队后续任务
    queue_dir = ledger.dispatch_keystroke_intent(
        session_id=sid,
        prompt_text="完成后顺便输出 benchmark 耗时报表",
        intent=KeyStrokeIntent.ALT_ENTER_ENQUEUE,
    )
    assert queue_dir is not None
    assert queue_dir.kind == LoopSteeringKind.OUTER_LOOP_FOLLOW_UP
    assert queue_dir.status == SteeringDirectiveStatus.PENDING

    # 3. 验证快照双队列隔离大盘
    snapshot: DualLoopQueueSnapshot = ledger.get_snapshot(sid, is_busy=True)
    assert snapshot.pending_inner_steer_count == 1
    assert snapshot.pending_outer_follow_up_count == 1
    assert snapshot.is_busy_navigating is True


def test_alt_up_recall_latest_follow_up_ergonomics() -> None:
    """测试 Alt+↑ 瞬间取回排队队列首项就地重新编辑的人体工学特性。"""
    ledger = DualLoopSessionQueueLedger()
    sid = "session_dual_02"

    # 连续排队两项任务
    ledger.dispatch_keystroke_intent(sid, "排队任务 1: 生成文档", KeyStrokeIntent.ALT_ENTER_ENQUEUE)
    ledger.dispatch_keystroke_intent(sid, "排队任务 2: 补充类型注解", KeyStrokeIntent.ALT_ENTER_ENQUEUE)

    snap1 = ledger.get_snapshot(sid)
    assert snap1.pending_outer_follow_up_count == 2

    # 用户在输入框按 Alt+↑ 取回最新排队的任务 2 就地修改
    recalled = ledger.dispatch_keystroke_intent(sid, "", KeyStrokeIntent.ALT_UP_RECALL_EDIT)
    assert recalled is not None
    assert recalled.prompt_text == "排队任务 2: 补充类型注解"
    assert recalled.status == SteeringDirectiveStatus.RECALLED

    # 验证队列仅剩任务 1
    snap2 = ledger.get_snapshot(sid)
    assert snap2.pending_outer_follow_up_count == 1
    assert snap2.outer_queue[0].prompt_text == "排队任务 1: 生成文档"

    # 再取回一次
    recalled2 = ledger.dispatch_keystroke_intent(sid, "", KeyStrokeIntent.ALT_UP_RECALL_EDIT)
    assert recalled2 is not None
    assert recalled2.prompt_text == "排队任务 1: 生成文档"

    # 队列已空，再次 Alt+↑ 安全返回 None
    assert ledger.dispatch_keystroke_intent(sid, "", KeyStrokeIntent.ALT_UP_RECALL_EDIT) is None


def test_inner_loop_pre_inference_steering_interceptor() -> None:
    """测试沙箱内核内层循环预推理代令装配：工具执行后原子装配代令，不停机即刻改向。"""
    ledger = DualLoopSessionQueueLedger()
    sid = "session_dual_03"

    # 初始上下文（用户指令 + 模型工具调用返回）
    active_messages = [
        {"role": "user", "content": "请重构认证模块"},
        {"role": "assistant", "content": "正在执行 find_files 扫描工程"},
        {"role": "tool", "content": "找到 auth.py, token.py"},
    ]

    # 用户中途代令改道
    ledger.dispatch_keystroke_intent(
        session_id=sid,
        prompt_text="优先保留既有的 JWT 验证逻辑，不要替换为 OAuth",
        intent=KeyStrokeIntent.ENTER_LIVE_STEER,
    )

    # 在触发下一轮 LLM 推理前，沙箱循环调用拦截器进行代令装配
    updated_messages, count = InnerLoopSteeringInterceptor.assemble_steered_context_turn(
        session_id=sid,
        active_messages=active_messages,
        ledger=ledger,
    )

    assert count == 1
    assert len(updated_messages) == 4
    last_msg = updated_messages[-1]
    assert last_msg["role"] == "user"
    assert "【用户实时中途代令纠偏 (Steering)】" in last_msg["content"]
    assert "优先保留既有的 JWT 验证逻辑" in last_msg["content"]

    # 验证再次调用时内层队列已排空，避免重复注入
    clean_messages, second_count = InnerLoopSteeringInterceptor.assemble_steered_context_turn(
        session_id=sid,
        active_messages=updated_messages,
        ledger=ledger,
    )
    assert second_count == 0
    assert len(clean_messages) == 4


def test_outer_loop_follow_up_execution_flow() -> None:
    """测试外层 Follow-Up 队列在主任务收敛后的 FIFO 顺次执行提取。"""
    ledger = DualLoopSessionQueueLedger()
    sid = "session_dual_04"

    ledger.dispatch_keystroke_intent(sid, "后续任务 A", KeyStrokeIntent.ALT_ENTER_ENQUEUE)
    ledger.dispatch_keystroke_intent(sid, "后续任务 B", KeyStrokeIntent.ALT_ENTER_ENQUEUE)

    # 顺次提取第 1 项
    item1 = ledger.pop_next_outer_follow_up(sid)
    assert item1 is not None
    assert item1.prompt_text == "后续任务 A"
    assert item1.status == SteeringDirectiveStatus.EXECUTED

    # 顺次提取第 2 项
    item2 = ledger.pop_next_outer_follow_up(sid)
    assert item2 is not None
    assert item2.prompt_text == "后续任务 B"
    assert item2.status == SteeringDirectiveStatus.EXECUTED

    # 提取完毕
    assert ledger.pop_next_outer_follow_up(sid) is None
