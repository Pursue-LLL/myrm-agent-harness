"""Archiving of procedural rules written by generators that no longer exist.

Rules built from a regex fragment of user text or from a system approval timeout
carry CRITICAL / USER_EXPLICIT trust yet never expire, so maintenance has to
retire them explicitly. Real SQLite store, no mocks.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.memory._internal.maintenance_rule_forgetting import forget_procedural_rules
from myrm_agent_harness.toolkits.memory.relational import SQLiteRelationalStore
from myrm_agent_harness.toolkits.memory.strategies.forgetting import (
    ForgettingConfig,
    ForgettingMode,
    ForgettingResult,
    ForgettingStrategy,
)
from myrm_agent_harness.toolkits.memory.types import ProceduralMemory, RuleSource, ToolRulePriority

_REGEX_DIRECTIVE = "Respect user directive: vision/snapshot"
_REGEX_EDICT = "Strictly follow user edict: sudo this time"
_TIMEOUT_FEEDBACK = "Consider alternative approach. User feedback: Auto-rejected: approval timeout (300s)"
_GENUINE_ACTION = "Never fabricate @dref values; take them from the latest desktop snapshot"


@pytest.fixture
async def store(tmp_path: Path) -> AsyncIterator[SQLiteRelationalStore]:
    relational = SQLiteRelationalStore(str(tmp_path / "memory.db"))
    yield relational
    await relational.close()


def _rule(
    action: str,
    *,
    source: RuleSource = RuleSource.USER_EXTRACTED,
    priority: ToolRulePriority = ToolRulePriority.CRITICAL,
    locked: bool = False,
) -> ProceduralMemory:
    return ProceduralMemory(
        content=action,
        trigger="some trigger",
        action=action,
        source=source,
        tool_rule_priority=priority,
        is_user_locked=locked,
    )


async def _run(
    store: SQLiteRelationalStore,
    *,
    mode: ForgettingMode = ForgettingMode.ARCHIVE,
    max_forget_per_run: int = 100,
) -> ForgettingResult:
    cfg = ForgettingConfig(mode=mode, max_forget_per_run=max_forget_per_run)
    result = ForgettingResult()
    await forget_procedural_rules(store, ForgettingStrategy(cfg), cfg, result, None)
    return result


async def _active_actions(store: SQLiteRelationalStore) -> list[str]:
    return sorted(r.action for r in await store.list_rules(active_only=True, limit=5000))


@pytest.mark.asyncio
async def test_rules_from_removed_generators_are_archived(store: SQLiteRelationalStore) -> None:
    created = [
        await store.create_rule(_rule(_REGEX_DIRECTIVE)),
        await store.create_rule(_rule(_REGEX_EDICT, source=RuleSource.USER_EXPLICIT)),
        await store.create_rule(_rule(_TIMEOUT_FEEDBACK, source=RuleSource.USER_EXPLICIT)),
    ]
    await store.create_rule(_rule(_GENUINE_ACTION))

    result = await _run(store)

    assert await _active_actions(store) == [_GENUINE_ACTION]
    assert result.archived_count == 3
    for rule in created:
        archived = await store.get_rule(rule.id)
        assert archived is not None
        assert archived.is_active is False
        assert archived.metadata["archive_reason"] == "legacy_generated_rule"
        assert "archive_expires_at" in archived.metadata


@pytest.mark.asyncio
async def test_user_locked_rule_is_never_archived(store: SQLiteRelationalStore) -> None:
    await store.create_rule(_rule(_REGEX_DIRECTIVE, source=RuleSource.USER_EXPLICIT, locked=True))

    await _run(store)

    assert await _active_actions(store) == [_REGEX_DIRECTIVE]


@pytest.mark.asyncio
async def test_archive_is_idempotent(store: SQLiteRelationalStore) -> None:
    await store.create_rule(_rule(_REGEX_DIRECTIVE))
    await store.create_rule(_rule(_GENUINE_ACTION))

    first = await _run(store)
    second = await _run(store)

    assert first.archived_count == 1
    assert second.archived_count == 0
    assert await _active_actions(store) == [_GENUINE_ACTION]


@pytest.mark.asyncio
async def test_scans_beyond_the_forgetting_window(store: SQLiteRelationalStore) -> None:
    """A store flooded with generated rules is cleaned in full, not just the first window."""
    for i in range(250):
        await store.create_rule(_rule(f"{_REGEX_DIRECTIVE} {i}"))
    await store.create_rule(_rule(_GENUINE_ACTION, priority=ToolRulePriority.NORMAL))

    result = await _run(store, max_forget_per_run=10)

    assert result.archived_count == 250
    assert await _active_actions(store) == [_GENUINE_ACTION]


@pytest.mark.asyncio
async def test_mark_mode_changes_nothing(store: SQLiteRelationalStore) -> None:
    await store.create_rule(_rule(_REGEX_DIRECTIVE))

    result = await _run(store, mode=ForgettingMode.MARK)

    assert result.archived_count == 0
    assert await _active_actions(store) == [_REGEX_DIRECTIVE]
