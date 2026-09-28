"""Unit tests for LocalWorkingMemoryBlock token estimation, sliding flush, and turn tail collapse.

[POS]
- tests/agent/context_management/test_working_memory_sliding_and_flush.py:
  验证 LocalWorkingMemoryBlock 的 Token 评估、滑动平滑淘汰、任务防护以及 Prompt 缓存友好折叠机制。
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.context_management.working_memory.block import (
    LocalWorkingMemoryBlock,
)
from myrm_agent_harness.agent.context_management.working_memory.types import (
    SubtaskStatus,
    WorkingMemoryFlushResult,
)


@pytest.fixture(autouse=True)
def clean_working_state() -> None:
    LocalWorkingMemoryBlock.reset()
    yield
    LocalWorkingMemoryBlock.reset()


def test_estimate_tokens_empty_and_populated() -> None:
    # 1. Empty state
    assert LocalWorkingMemoryBlock.estimate_tokens() == 0

    # 2. Populated state
    LocalWorkingMemoryBlock.initialize(
        goal="Develop High Performance Memory Subsystem",
        initial_subtasks=["Analyze hot spots", "Implement LRU eviction"],
    )
    est = LocalWorkingMemoryBlock.estimate_tokens()
    assert est > 0

    LocalWorkingMemoryBlock.set_scratchpad("temp_var", "some_important_observation")
    est_after = LocalWorkingMemoryBlock.estimate_tokens()
    assert est_after > est


def test_flush_stale_under_budget_preserves_everything() -> None:
    LocalWorkingMemoryBlock.initialize(
        goal="Maintain budget discipline",
        initial_subtasks=["Step 1", "Step 2"],
    )
    LocalWorkingMemoryBlock.update_subtask("step-1", SubtaskStatus.COMPLETED)
    LocalWorkingMemoryBlock.set_scratchpad("k1", "v1")

    # High budget: no eviction should occur
    result: WorkingMemoryFlushResult = LocalWorkingMemoryBlock.flush_stale(
        flush_ratio=0.5, token_budget=5000
    )
    assert result.evicted_subtasks_count == 0
    assert result.evicted_scratchpad_count == 0
    assert result.remaining_subtasks_count == 2
    assert result.remaining_scratchpad_count == 1
    assert result.estimated_tokens_before == result.estimated_tokens_after


def test_flush_stale_eviction_protects_critical_tasks_and_traps() -> None:
    LocalWorkingMemoryBlock.initialize(goal="Core critical mission")

    # Add 4 completed subtasks
    for i in range(1, 5):
        s = LocalWorkingMemoryBlock.add_subtask(f"Done Task {i}", subtask_id=f"done-{i}")
        assert s is not None
        LocalWorkingMemoryBlock.update_subtask(s.id, SubtaskStatus.COMPLETED)

    # Add active, pending, and failed tasks
    s_active = LocalWorkingMemoryBlock.add_subtask("Active Task", subtask_id="active-1")
    assert s_active is not None
    LocalWorkingMemoryBlock.update_subtask(s_active.id, SubtaskStatus.IN_PROGRESS)

    s_pending = LocalWorkingMemoryBlock.add_subtask("Pending Task", subtask_id="pending-1")
    assert s_pending is not None
    LocalWorkingMemoryBlock.update_subtask(s_pending.id, SubtaskStatus.PENDING)

    s_failed = LocalWorkingMemoryBlock.add_subtask("Failed Task", subtask_id="failed-1")
    assert s_failed is not None
    LocalWorkingMemoryBlock.update_subtask(s_failed.id, SubtaskStatus.FAILED)

    # Add traps (resolved and unresolved)
    LocalWorkingMemoryBlock.record_trap("trap_1", "Rule for trap 1")
    LocalWorkingMemoryBlock.record_trap("trap_2", "Rule for trap 2")
    LocalWorkingMemoryBlock.resolve_trap("trap_1")

    # Add scratchpad
    for idx in range(4):
        LocalWorkingMemoryBlock.set_scratchpad(f"var_{idx}", f"val_{idx}")

    # Evict 50% of completed tasks
    res = LocalWorkingMemoryBlock.flush_stale(flush_ratio=0.5)

    assert res.evicted_subtasks_count == 2
    state = LocalWorkingMemoryBlock.get_state()
    assert state is not None

    remaining_ids = {s.id for s in state.subtasks}
    # Oldest 2 completed tasks evicted
    assert "done-1" not in remaining_ids
    assert "done-2" not in remaining_ids
    # Newer 2 completed tasks retained
    assert "done-3" in remaining_ids
    assert "done-4" in remaining_ids

    # Critical tasks NEVER evicted
    assert "active-1" in remaining_ids
    assert "pending-1" in remaining_ids
    assert "failed-1" in remaining_ids

    # Goal and traps NEVER evicted
    assert state.goal == "Core critical mission"
    assert len(state.traps) == 2


def test_format_turn_tail_sliding_collapse() -> None:
    LocalWorkingMemoryBlock.initialize(goal="Test sliding collapse")

    # Add 5 completed subtasks
    for i in range(1, 6):
        item = LocalWorkingMemoryBlock.add_subtask(f"Subtask {i}", subtask_id=f"step-{i}")
        assert item is not None
        LocalWorkingMemoryBlock.update_subtask(item.id, SubtaskStatus.COMPLETED)

    # Add 1 in-progress subtask
    active = LocalWorkingMemoryBlock.add_subtask("Current Subtask", subtask_id="step-active")
    assert active is not None
    LocalWorkingMemoryBlock.update_subtask(active.id, SubtaskStatus.IN_PROGRESS)

    # 1. Under comfortable budget: all steps rendered without collapse
    uncollapsed_md = LocalWorkingMemoryBlock.format_turn_tail_markdown(token_budget=1000)
    assert "[5 prior completed subtasks collapsed]" not in uncollapsed_md
    assert "step-1" in uncollapsed_md
    assert "step-5" in uncollapsed_md
    assert "step-active" in uncollapsed_md

    # 2. Under tight budget: older completed steps collapsed, leaving the most recent completed step
    collapsed_md = LocalWorkingMemoryBlock.format_turn_tail_markdown(token_budget=10)
    assert "- ✓ [4 prior completed subtasks collapsed]" in collapsed_md
    assert "step-1" not in collapsed_md
    assert "step-4" not in collapsed_md
    assert "step-5" in collapsed_md
    assert "step-active" in collapsed_md


def test_format_turn_tail_trap_icons_and_limit() -> None:
    LocalWorkingMemoryBlock.initialize(goal="Trap rendering")
    LocalWorkingMemoryBlock.record_trap("t1", "Prior trap rule", tool_name="fs_read")
    LocalWorkingMemoryBlock.advance_turn()
    LocalWorkingMemoryBlock.record_trap("t2", "Active trap rule", tool_name="bash_exec")
    LocalWorkingMemoryBlock.record_trap("t3", "Resolved trap rule", tool_name="sql_exec")
    LocalWorkingMemoryBlock.resolve_trap("t3")

    rendered = LocalWorkingMemoryBlock.format_turn_tail_markdown(max_traps=2)
    # Only last 2 traps shown
    assert "t1" not in rendered
    assert "Active trap rule" in rendered
    assert "Resolved trap rule" in rendered
    assert "✅ [Resolved] [sql_exec] Resolved trap rule" in rendered
    assert "⚠️ [bash_exec] Active trap rule" in rendered
