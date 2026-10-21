"""Unit tests for LocalWorkingMemoryBlock token estimation and turn tail rendering.

[POS]
- tests/agent/context_management/test_working_memory_token_estimation_and_turn_tail.py:
  验证 LocalWorkingMemoryBlock 的 Token 评估、Turn Tail 渲染与 Prompt 缓存友好折叠机制。
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.context_management.working_memory.block import (
    LocalWorkingMemoryBlock,
)
from myrm_agent_harness.agent.context_management.working_memory.types import (
    SubtaskStatus,
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
