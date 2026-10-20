"""Focused tests for delegate_task 60s result cache helpers."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import (
    _cache_key,
    _CachedResult,
    _get_cached,
    _put_cache,
    _result_cache,
)


def test_cache_key_includes_effective_readonly() -> None:
    writable = _cache_key("coder", "task", None, session_id="s1", effective_readonly=False)
    readonly = _cache_key("coder", "task", None, session_id="s1", effective_readonly=True)
    assert writable != readonly


def test_put_get_and_expire() -> None:
    _result_cache.clear()
    _put_cache("ttl-key", {"value": 1})
    assert _get_cached("ttl-key") == {"value": 1}

    _result_cache["stale-key"] = _CachedResult({"old": True}, time.time() - 120)
    assert _get_cached("stale-key") is None
    assert "stale-key" not in _result_cache
    _result_cache.clear()


def test_put_cache_evicts_expired_and_oldest() -> None:
    from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import (
        _CACHE_MAX_SIZE,
    )

    _result_cache.clear()
    now = time.time()
    for idx in range(_CACHE_MAX_SIZE):
        _result_cache[f"key-{idx}"] = _CachedResult({"idx": idx}, now - idx)
    _result_cache["expired"] = _CachedResult({"gone": True}, now - 120)

    _put_cache("fresh", {"new": True})
    assert _get_cached("fresh") == {"new": True}
    assert _get_cached("expired") is None
    _result_cache.clear()


def test_get_hashable_value_and_payload_hash() -> None:
    from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import (
        _compute_payload_hash,
        _get_hashable_value,
    )

    nested = _get_hashable_value({"a": [1, {"b": object()}]})
    assert nested["a"][1]["b"]  # coerced to str

    digest = _compute_payload_hash(
        "coder",
        "task",
        "leaf",
        {"ctx": {"n": 1}},
    )
    assert len(digest) == 64


def test_normalize_role_invalid_falls_back_to_leaf() -> None:
    from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import (
        _normalize_role,
    )
    from myrm_agent_harness.agent.sub_agents.types import DelegateRole

    assert _normalize_role("not-a-role") is DelegateRole.LEAF


@pytest.mark.asyncio
async def test_admit_race_budget_coerces_invalid_budget_status_string() -> None:

    from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import (
        _admit_race_budget,
    )
    from myrm_agent_harness.agent.sub_agents.types import SubagentConfig

    checker = MagicMock()
    checker.check_budget.return_value = "not-a-status"

    parent = MagicMock()
    parent.token_tracker = MagicMock()
    parent.token_tracker.budget_checker = checker
    parent.config = MagicMock()
    parent.config.llm = MagicMock()
    parent.config.llm.model_name = "gpt-4"

    catalog = AsyncMock()
    catalog.resolve = AsyncMock(
        return_value=SubagentConfig(system_prompt="test", max_cost_usd=0.05)
    )

    task = MagicMock()
    task.agent_type = "search"

    result = await _admit_race_budget(parent_agent=parent, catalog=catalog, tasks=[task])
    assert result.status == "admitted"
