"""Tests for load_context stable-layer filtering of tool-failure rules.

Validates that transient NORMAL-priority failure rules (origin=tool_failure)
stay out of the stable ``agent_instructions`` layer while user-explicit
instructions and CRITICAL/HIGH rules are unaffected.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.toolkits.memory._internal.storage_context import load_context
from myrm_agent_harness.toolkits.memory.types import (
    ProceduralMemory,
    RuleSource,
    ToolRulePriority,
)


def _failure_rule(
    *,
    priority: ToolRulePriority = ToolRulePriority.NORMAL,
    origin: str = "tool_failure",
) -> ProceduralMemory:
    return ProceduralMemory(
        content="Tool 'web_fetch_tool' failed 2 times in this session",
        trigger="web_fetch_tool repeated failure",
        action="Consider alternative approach when using web_fetch_tool.",
        tool_name="web_fetch_tool",
        tool_rule_priority=priority,
        source=RuleSource.AGENT_SELF,
        expected_valid_days=1,
        metadata={"origin": origin},
    )


@pytest.mark.asyncio
async def test_tool_failure_rule_excluded_from_stable_layer() -> None:
    """NORMAL tool-failure rules never reach stable agent_instructions."""
    relational = AsyncMock()
    relational.list_profiles.return_value = []
    relational.list_rules.return_value = [_failure_rule()]

    ctx = await load_context(relational)

    assert ctx["agent_instructions"] == []
    assert ctx["rules"] == []


@pytest.mark.asyncio
async def test_user_explicit_agent_self_instruction_kept() -> None:
    """User-saved AGENT_SELF instructions (no origin marker) stay in stable."""
    relational = AsyncMock()
    relational.list_profiles.return_value = []
    relational.list_rules.return_value = [
        ProceduralMemory(
            content="self instruction",
            trigger="trigger",
            action="Always write tests first",
            source=RuleSource.AGENT_SELF,
        )
    ]

    ctx = await load_context(relational)

    assert ctx["agent_instructions"] == [
        {"instruction": "Always write tests first", "priority": 0}
    ]


@pytest.mark.asyncio
async def test_critical_tool_failure_rule_kept() -> None:
    """CRITICAL-priority rules are pinned into stable even with failure origin."""
    relational = AsyncMock()
    relational.list_profiles.return_value = []
    relational.list_rules.return_value = [_failure_rule(priority=ToolRulePriority.CRITICAL)]

    ctx = await load_context(relational)

    assert len(ctx["agent_instructions"]) == 1
    assert ctx["agent_instructions"][0]["instruction"].startswith(
        "Consider alternative approach"
    )


@pytest.mark.asyncio
async def test_mixed_rules_partitioned_correctly() -> None:
    """Failure rules filtered; explicit instructions kept in the same batch."""
    relational = AsyncMock()
    relational.list_profiles.return_value = []
    relational.list_rules.return_value = [
        _failure_rule(),
        ProceduralMemory(
            content="self instruction",
            trigger="trigger",
            action="Follow project conventions",
            source=RuleSource.AGENT_SELF,
        ),
    ]

    ctx = await load_context(relational)

    assert len(ctx["agent_instructions"]) == 1
    assert ctx["agent_instructions"][0]["instruction"] == "Follow project conventions"


@pytest.mark.asyncio
async def test_user_locked_tool_failure_rule_kept() -> None:
    """A user-edited (locked) tool-failure rule graduates into the stable layer.

    Editing an auto-generated failure rule is an explicit endorsement: the rule
    should steer tool selection like any other user-approved AGENT_SELF instruction.
    """
    relational = AsyncMock()
    relational.list_profiles.return_value = []
    relational.list_rules.return_value = [
        ProceduralMemory(
            content="web_fetch_tool is unstable here, prefer curl retry",
            trigger="web_fetch_tool repeated failure",
            action="Use curl retry before web_fetch_tool",
            tool_name="web_fetch_tool",
            tool_rule_priority=ToolRulePriority.NORMAL,
            source=RuleSource.AGENT_SELF,
            expected_valid_days=1,
            metadata={"origin": "tool_failure"},
            is_user_locked=True,
        )
    ]

    ctx = await load_context(relational)

    assert ctx["agent_instructions"] == [
        {"instruction": "Use curl retry before web_fetch_tool", "priority": 0}
    ]


@pytest.mark.asyncio
async def test_locked_failure_rule_kept_alongside_auto_failure_rule() -> None:
    """Locked failure rules are promoted while untouched auto rules stay filtered."""
    relational = AsyncMock()
    relational.list_profiles.return_value = []
    relational.list_rules.return_value = [
        _failure_rule(),
        ProceduralMemory(
            content="web_fetch_tool is unstable here, prefer curl retry",
            trigger="web_fetch_tool repeated failure",
            action="Use curl retry before web_fetch_tool",
            tool_name="web_fetch_tool",
            tool_rule_priority=ToolRulePriority.NORMAL,
            source=RuleSource.AGENT_SELF,
            expected_valid_days=1,
            metadata={"origin": "tool_failure"},
            is_user_locked=True,
        ),
    ]

    ctx = await load_context(relational)

    assert ctx["agent_instructions"] == [
        {"instruction": "Use curl retry before web_fetch_tool", "priority": 0}
    ]
