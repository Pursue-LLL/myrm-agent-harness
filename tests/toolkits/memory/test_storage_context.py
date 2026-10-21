"""Tests for load_context rule partitioning.

Agent-authored rules feed ``agent_instructions``, user rules feed ``rules`` (locked
rules first), and tool-bound rules are additionally exposed as guidance items.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.toolkits.memory._internal.storage_context import load_context
from myrm_agent_harness.toolkits.memory.types import (
    ProceduralMemory,
    RuleSource,
)


def _relational(rules: list[ProceduralMemory]) -> AsyncMock:
    relational = AsyncMock()
    relational.list_profiles.return_value = []
    relational.list_rules.return_value = rules
    return relational


@pytest.mark.asyncio
async def test_agent_self_rule_goes_to_agent_instructions() -> None:
    relational = _relational(
        [
            ProceduralMemory(
                content="self instruction",
                trigger="trigger",
                action="Always write tests first",
                source=RuleSource.AGENT_SELF,
            )
        ]
    )

    ctx = await load_context(relational)

    assert ctx["agent_instructions"] == [{"instruction": "Always write tests first", "priority": 0}]
    assert ctx["rules"] == []


@pytest.mark.asyncio
async def test_user_rules_list_locked_rules_first() -> None:
    relational = _relational(
        [
            ProceduralMemory(content="a", trigger="when A", action="do A", source=RuleSource.USER_EXTRACTED),
            ProceduralMemory(
                content="b",
                trigger="when B",
                action="do B",
                source=RuleSource.USER_EXPLICIT,
                is_user_locked=True,
            ),
        ]
    )

    ctx = await load_context(relational)

    assert [rule["action"] for rule in ctx["rules"]] == ["do B", "do A"]
    assert [rule["user_endorsed"] for rule in ctx["rules"]] == [True, False]
    assert ctx["agent_instructions"] == []


@pytest.mark.asyncio
async def test_tool_bound_rule_is_also_exposed_as_guidance_item() -> None:
    relational = _relational(
        [
            ProceduralMemory(
                content="fetch retry",
                trigger="web_fetch_tool times out",
                action="Retry once with a longer timeout",
                tool_name="web_fetch_tool",
                source=RuleSource.USER_EXTRACTED,
            ),
            ProceduralMemory(content="plain", trigger="always", action="Be concise", source=RuleSource.USER_EXTRACTED),
        ]
    )

    ctx = await load_context(relational)

    items = ctx["raw_tool_guidance_items"]
    assert [(item.tool_name, item.rule_text) for item in items] == [
        ("web_fetch_tool", "Retry once with a longer timeout")
    ]
    assert len(ctx["rules"]) == 2
