# [POS] myrm-agent-harness/tests/test_budget_curator.py
# [INPUT] AtomicOperationsCurator, MemoryBudgetMeter, SessionScrollNavigator, types from budget_curator
# [OUTPUT] 记忆预算仪表盘、原子批量腾挪策展操作符与长程会话回溯锚点完整单元测试

"""记忆预算仪表盘、原子批量腾挪策展操作符与长程会话回溯锚点单元测试。"""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.memory.budget_curator import (
    AtomicOperationsCurator,
    ManagedMemoryItem,
    MemoryBatchOperation,
    MemoryBudgetMeter,
    MemoryBudgetSpec,
    MemoryOperationType,
    ScrollAnchorRequest,
    ScrollMessageItem,
    SessionScrollNavigator,
)


def test_memory_budget_meter_header_and_overflow() -> None:
    """测试记忆预算计量器的标头格式化、利用率与溢出告警。"""
    spec = MemoryBudgetSpec(max_tokens=100, max_slots=5, warning_threshold_pct=70.0)
    meter = MemoryBudgetMeter(spec=spec)

    # 1. 正常状态
    items = [
        ManagedMemoryItem("m1", "偏好使用 Python 3.13", 20),
        ManagedMemoryItem("m2", "代码风格严格遵循 PEP8", 30),
    ]
    status = meter.evaluate_budget(items)
    assert status.used_tokens == 50
    assert status.used_slots == 2
    assert status.token_usage_pct == 50.0
    assert status.is_warning is False
    assert status.is_overflow is False
    assert "# USER PROFILE & MEMORIES [Budget: 50%, 50/100 tokens | Slots: 2/5]" in status.budget_header_slice

    # 2. 预警状态 (占用 75%)
    items_warn = [*items, ManagedMemoryItem("m3", "沙箱单机运行策略", 25)]
    status_warn = meter.evaluate_budget(items_warn)
    assert status_warn.is_warning is True
    assert status_warn.is_overflow is False
    assert "[WARNING - NEAR CAPACITY]" in status_warn.budget_header_slice

    # 3. 溢出状态 (占用 110%)
    items_overflow = [*items_warn, ManagedMemoryItem("m4", "额外超长上下文说明", 35)]
    status_overflow = meter.evaluate_budget(items_overflow)
    assert status_overflow.is_overflow is True
    assert "[EXCEEDED - CLEANUP REQUIRED]" in status_overflow.budget_header_slice


def test_atomic_operations_curator_successful_swap() -> None:
    """测试原子批量腾挪操作符：删旧加新在单次事务中成功提交。"""
    spec = MemoryBudgetSpec(max_tokens=100, max_slots=5)
    curator = AtomicOperationsCurator(spec=spec)

    initial_items = [
        ManagedMemoryItem("old_1", "废弃的配置方案 A", 30),
        ManagedMemoryItem("keep_1", "长效事实偏好 B", 20),
    ]

    ops = [
        MemoryBatchOperation(
            operation_type=MemoryOperationType.REMOVE,
            target_id="old_1",
        ),
        MemoryBatchOperation(
            operation_type=MemoryOperationType.ADD,
            new_id="new_1",
            new_content="新采纳的优化方案 C",
            estimated_tokens=35,
        ),
    ]

    result = curator.apply_operations(initial_items, ops)
    assert result.is_success is True
    assert result.rolled_back is False
    assert result.applied_count == 2
    assert len(result.retained_items) == 2
    assert any(it.item_id == "new_1" for it in result.retained_items)
    assert not any(it.item_id == "old_1" for it in result.retained_items)
    assert result.current_budget.used_tokens == 55


def test_atomic_operations_curator_overflow_rollback() -> None:
    """测试容量越界时彻底原子回滚，杜绝半成功坏账。"""
    spec = MemoryBudgetSpec(max_tokens=60, max_slots=3)
    curator = AtomicOperationsCurator(spec=spec)

    initial_items = [
        ManagedMemoryItem("item_a", "重要事实 A", 25),
        ManagedMemoryItem("item_b", "重要事实 B", 25),
    ]

    # 该操作试图添加一个 30 tokens 的项，导致总 token 变为 25+25+30=80 > 60
    ops = [
        MemoryBatchOperation(
            operation_type=MemoryOperationType.ADD,
            new_id="item_c",
            new_content="超大事实 C",
            estimated_tokens=30,
        ),
    ]

    result = curator.apply_operations(initial_items, ops)
    assert result.is_success is False
    assert result.rolled_back is True
    assert "memory budget overflowed" in result.error_message
    # 原数据丝毫不受影响
    assert len(result.retained_items) == 2
    assert result.retained_items[0].item_id == "item_a"
    assert result.retained_items[1].item_id == "item_b"


def test_atomic_operations_curator_substring_collision_guard() -> None:
    """测试通过短子串匹配时若发生歧义命中多条，触发防误删门禁并全回滚。"""
    spec = MemoryBudgetSpec(max_tokens=200, max_slots=10)
    curator = AtomicOperationsCurator(spec=spec)

    initial_items = [
        ManagedMemoryItem("opt_1", "系统配置: 开启调试日志模式", 20),
        ManagedMemoryItem("opt_2", "系统配置: 开启实时监控模式", 20),
    ]

    # 用模糊子串 "系统配置" 试图删除，会命中 opt_1 与 opt_2
    ops = [
        MemoryBatchOperation(
            operation_type=MemoryOperationType.REMOVE,
            target_substring="系统配置",
        ),
    ]

    result = curator.apply_operations(initial_items, ops)
    assert result.is_success is False
    assert result.rolled_back is True
    assert "matched multiple candidates" in result.error_message
    assert "opt_1" in result.error_message and "opt_2" in result.error_message
    assert len(result.retained_items) == 2


def test_session_scroll_navigator_window() -> None:
    """测试围绕 message_id 的双向滑动窗口精准拉取与分页边界。"""
    messages = [
        ScrollMessageItem(f"msg_{i}", "user" if i % 2 == 0 else "assistant", f"content {i}", f"2026-10-07T0{i}:00:00Z")
        for i in range(10)
    ]

    # 1. 围绕 msg_5 拉取前后各 2 条 (区间 [3, 7])
    req = ScrollAnchorRequest(
        conversation_id="conv-1",
        around_message_id="msg_5",
        before_limit=2,
        after_limit=2,
    )
    res = SessionScrollNavigator.scroll_around_message(messages, req)
    assert len(res.messages) == 5
    assert res.messages[0].message_id == "msg_3"
    assert res.messages[2].message_id == "msg_5"
    assert res.messages[4].message_id == "msg_7"
    assert res.has_more_before is True
    assert res.has_more_after is True

    # 2. 围绕 msg_0 (开头边界)
    req_start = ScrollAnchorRequest(
        conversation_id="conv-1",
        around_message_id="msg_0",
        before_limit=3,
        after_limit=2,
    )
    res_start = SessionScrollNavigator.scroll_around_message(messages, req_start)
    assert res_start.has_more_before is False
    assert res_start.has_more_after is True
    assert res_start.messages[0].message_id == "msg_0"

    # 3. 围绕不存在的 ID 抛出 KeyError
    req_missing = ScrollAnchorRequest(
        conversation_id="conv-1",
        around_message_id="msg_999",
    )
    with pytest.raises(KeyError, match="Anchor message_id 'msg_999' not found"):
        SessionScrollNavigator.scroll_around_message(messages, req_missing)
