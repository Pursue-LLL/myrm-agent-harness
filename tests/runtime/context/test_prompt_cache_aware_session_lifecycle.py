"""Unit tests for Prompt-cache aware session lifecycle and prefix preserving router.

Verifies canonical tool sorting, byte-stable prefix fingerprinting, in-session mutation
risk evaluations, cache-friendly tail rewind, and pre-idle compaction planning.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.runtime.context.cache_aware_session_lifecycle_router import (
    CacheAwareSessionLifecycleRouter,
)
from myrm_agent_harness.runtime.context.prefix_preserving_canonicalizer import (
    PrefixPreservingCanonicalizer,
)
from myrm_agent_harness.runtime.context.prompt_cache_lifecycle_types import (
    CacheMutationRiskLevel,
    CompactionTimingUrgency,
)


@pytest.fixture
def sample_tools() -> list[dict[str, str]]:
    """Sample tool definition schemas in unsorted order."""
    return [
        {"name": "write_file", "description": "Write contents to a file."},
        {"name": "read_file", "description": "Read file contents from workspace."},
        {"name": "execute_command", "description": "Execute bash commands in sandbox."},
    ]


@pytest.fixture
def sample_ten_turn_messages() -> list[dict[str, str]]:
    """Generates a realistic 10-turn dialogue for rewind testing."""
    return [
        {"role": "user", "content": f"Turn {i}: user instruction payload."}
        if i % 2 == 1
        else {"role": "assistant", "content": f"Turn {i}: assistant resolution step."}
        for i in range(1, 11)
    ]


def test_canonical_tool_sorting_and_prefix_fingerprint(
    sample_tools: list[dict[str, str]],
) -> None:
    """Tools in different initial orders must produce identical canonical hashes."""
    canonicalizer = PrefixPreservingCanonicalizer()

    shuffled_tools = [sample_tools[1], sample_tools[2], sample_tools[0]]

    fp1 = canonicalizer.compute_prefix_fingerprint(
        tools=sample_tools,
        system_prompt="You are a senior systems engineer.",
        persona="Dr. Vance",
    )
    fp2 = canonicalizer.compute_prefix_fingerprint(
        tools=shuffled_tools,
        system_prompt="You are a senior systems engineer.",
        persona="Dr. Vance",
    )

    assert fp1.combined_fingerprint == fp2.combined_fingerprint
    assert fp1.tool_registry_hash == fp2.tool_registry_hash

    is_continuous, reason = canonicalizer.verify_prefix_continuity(fp1, fp2)
    assert is_continuous is True
    assert "100% cache preservation" in reason


def test_prefix_drift_detection(sample_tools: list[dict[str, str]]) -> None:
    """Mutating system prompt or persona must be detected as prefix drift."""
    canonicalizer = PrefixPreservingCanonicalizer()

    baseline = canonicalizer.compute_prefix_fingerprint(
        tools=sample_tools,
        system_prompt="You are a systems engineer.",
        persona="Dr. Vance",
    )
    mutated = canonicalizer.compute_prefix_fingerprint(
        tools=sample_tools,
        system_prompt="You are a modified systems engineer.",
        persona="Dr. Vance",
    )

    is_continuous, reason = canonicalizer.verify_prefix_continuity(baseline, mutated)
    assert is_continuous is False
    assert "system_prompt_text_mutated" in reason


def test_in_session_mutation_risk_audit() -> None:
    """Switching models or reasoning effort mid-session must trigger risk reports."""
    router = CacheAwareSessionLifecycleRouter()

    # Model switch triggers DANGEROUS risk report
    report_model = router.evaluate_mutation_risk(
        current_model="claude-3-7-sonnet",
        proposed_model="gpt-4o",
        cached_prefix_tokens=15000,
    )
    assert report_model.risk_level == CacheMutationRiskLevel.DANGEROUS
    assert report_model.is_mutation_destructive is True
    assert report_model.wasted_prefill_tokens == 15000
    assert report_model.estimated_cost_multiplier >= 10.0
    assert "destroys 15000 cached tokens" in report_model.recommendation

    # Effort level change triggers WARNING report
    report_effort = router.evaluate_mutation_risk(
        current_model="claude-3-7-sonnet",
        proposed_model="claude-3-7-sonnet",
        cached_prefix_tokens=15000,
        current_effort="medium",
        proposed_effort="high",
    )
    assert report_effort.risk_level == CacheMutationRiskLevel.WARNING
    assert report_effort.is_mutation_destructive is False

    # Identical parameters trigger SAFE report
    report_safe = router.evaluate_mutation_risk(
        current_model="claude-3-7-sonnet",
        proposed_model="claude-3-7-sonnet",
        cached_prefix_tokens=15000,
        current_effort="medium",
        proposed_effort="medium",
    )
    assert report_safe.risk_level == CacheMutationRiskLevel.SAFE
    assert report_safe.estimated_cost_multiplier == 1.0


def test_cache_friendly_tail_rewind(sample_ten_turn_messages: list[dict[str, str]]) -> None:
    """Tail rewind must prune recent turns while preserving early prefix turns verbatim."""
    router = CacheAwareSessionLifecycleRouter()

    retained, receipt = router.rewind_tail(
        messages=sample_ten_turn_messages,
        turns_to_prune=3,
    )

    assert len(retained) == 7
    assert receipt.original_turn_count == 10
    assert receipt.pruned_turn_count == 3
    assert receipt.remaining_turn_count == 7
    assert receipt.cache_preserved is True
    assert receipt.preserved_prefix_tokens > 0

    # Ensure prefix items are verbatim identical
    for i in range(7):
        assert retained[i]["content"] == sample_ten_turn_messages[i]["content"]


def test_pre_idle_compaction_planning() -> None:
    """Compaction must be planned opportunistically or immediately based on TTL windows."""
    router = CacheAwareSessionLifecycleRouter(
        default_cache_ttl_seconds=3600.0,
        idle_compaction_threshold_seconds=180.0,
    )

    # Case 1: Session idle for 200s with plenty of TTL left -> OPPORTUNISTIC
    plan_opp = router.plan_pre_idle_compaction(session_idle_seconds=200.0)
    assert plan_opp.urgency == CompactionTimingUrgency.OPPORTUNISTIC
    assert plan_opp.should_execute is True
    assert "0.1x price" in plan_opp.strategy

    # Case 2: TTL running out (remaining < 300s) -> IMMEDIATE
    plan_imm = router.plan_pre_idle_compaction(
        session_idle_seconds=3400.0,
        cached_ttl_seconds=3600.0,
    )
    assert plan_imm.urgency == CompactionTimingUrgency.IMMEDIATE
    assert plan_imm.should_execute is True

    # Case 3: Recently active (idle < 180s) -> NOT_NEEDED
    plan_active = router.plan_pre_idle_compaction(session_idle_seconds=30.0)
    assert plan_active.urgency == CompactionTimingUrgency.NOT_NEEDED
    assert plan_active.should_execute is False

    # Case 4: Cache already expired -> NOT_NEEDED
    plan_expired = router.plan_pre_idle_compaction(
        session_idle_seconds=3700.0,
        cached_ttl_seconds=3600.0,
    )
    assert plan_expired.urgency == CompactionTimingUrgency.NOT_NEEDED
    assert plan_expired.should_execute is False
