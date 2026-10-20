"""delegate_task call fingerprint, role normalization and race budget admission helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import (
    _admit_race_budget,
    _compute_payload_hash,
    _get_hashable_value,
    _normalize_role,
)
from myrm_agent_harness.agent.sub_agents.types import DelegateRole, SubagentConfig


def _fingerprint(
    task: str = "task",
    context: dict[str, object] | None = None,
    *,
    effective_readonly: bool = False,
    complexity_tier: str | None = None,
    verifier_prompt: str | None = None,
    verifier_agent_type: str | None = None,
    max_verification_rounds: int = 2,
) -> str:
    return _compute_payload_hash(
        "coder",
        task,
        "leaf",
        context,
        effective_readonly=effective_readonly,
        complexity_tier=complexity_tier,
        verifier_prompt=verifier_prompt,
        verifier_agent_type=verifier_agent_type,
        max_verification_rounds=max_verification_rounds,
    )


def test_get_hashable_value_coerces_unserializable_leaves_to_str() -> None:
    nested = _get_hashable_value({"a": [1, {"b": object()}]})
    assert nested["a"][1]["b"]  # coerced to str


def test_fingerprint_is_a_stable_sha256() -> None:
    digest = _fingerprint(context={"ctx": {"n": 1}})
    assert len(digest) == 64
    assert digest == _fingerprint(context={"ctx": {"n": 1}})


def test_fingerprint_ignores_context_key_order() -> None:
    first = _fingerprint(context={"a": 1, "b": {"x": 1, "y": 2}})
    reordered = _fingerprint(context={"b": {"y": 2, "x": 1}, "a": 1})
    assert first == reordered


def test_fingerprint_survives_lone_surrogates_and_stays_deterministic() -> None:
    first = _fingerprint("fix \ud800 bug", {"note": "\udfff"})
    again = _fingerprint("fix \ud800 bug", {"note": "\udfff"})
    other = _fingerprint("fix \ud801 bug", {"note": "\udfff"})

    assert first == again
    assert first != other


def test_fingerprint_changes_when_the_delegation_runs_differently() -> None:
    base = _fingerprint()

    assert _fingerprint(effective_readonly=True) != base
    assert _fingerprint(complexity_tier="reasoning") != base
    assert _fingerprint(verifier_prompt="Verify it") != base


def test_fingerprint_treats_an_empty_tier_as_no_tier() -> None:
    assert _fingerprint(complexity_tier="") == _fingerprint(complexity_tier=None)


def test_fingerprint_counts_verifier_options_only_when_a_verification_is_requested() -> None:
    assert _fingerprint(verifier_agent_type="reviewer", max_verification_rounds=4) == _fingerprint()

    verified = _fingerprint(verifier_prompt="Verify it")
    assert _fingerprint(verifier_prompt="Verify it", verifier_agent_type="reviewer") != verified
    assert _fingerprint(verifier_prompt="Verify it", max_verification_rounds=4) != verified


def test_normalize_role_invalid_falls_back_to_leaf() -> None:
    assert _normalize_role("not-a-role") is DelegateRole.LEAF


@pytest.mark.asyncio
async def test_admit_race_budget_coerces_invalid_budget_status_string() -> None:
    checker = MagicMock()
    checker.check_budget.return_value = "not-a-status"

    parent = MagicMock()
    parent.token_tracker = MagicMock()
    parent.token_tracker.budget_checker = checker
    parent.config = MagicMock()
    parent.config.llm = MagicMock()
    parent.config.llm.model_name = "gpt-4"

    catalog = AsyncMock()
    catalog.resolve = AsyncMock(return_value=SubagentConfig(system_prompt="test", max_cost_usd=0.05))

    task = MagicMock()
    task.agent_type = "search"

    result = await _admit_race_budget(parent_agent=parent, catalog=catalog, tasks=[task])
    assert result.status == "admitted"
