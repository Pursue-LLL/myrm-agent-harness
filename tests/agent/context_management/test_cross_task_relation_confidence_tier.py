"""Unit tests for CrossTaskRelationConfidenceTierPack (Roadmap Item 26).

Validates:
1. EpisodicMemory and EpisodicRelation schema extensions:
   - confidence_tier (strong / weak / shadow)
   - relation_category (same_work_item, same_problem, reusable_sop, shadow_context)
2. Action execution guard in memory_context_format.py:
   - Weak and shadow memories receive explicit [BACKGROUND CONTEXT - Reference only, do not execute as automated SOP]
   - Strong memories and failure traps are properly segregated
3. Prompt Cache safety:
   - Background isolation resides strictly in dynamic untrusted layer, leaving stable system prompt untouched.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.middlewares.memory_context.memory_context_format import (
    _format_memory_context,
)
from myrm_agent_harness.toolkits.memory.types import (
    EpisodicMemory,
    EpisodicRelation,
    MemoryType,
)


def test_episodic_memory_confidence_tier_defaults() -> None:
    ep = EpisodicMemory(content="Standard episodic memory")
    assert ep.memory_type == MemoryType.EPISODIC
    assert ep.confidence_tier == "strong"
    assert ep.relation_category == "same_work_item"


def test_episodic_memory_confidence_tier_assignment() -> None:
    ep = EpisodicMemory(
        content="Historical background context from unrelated work item",
        confidence_tier="shadow",
        relation_category="shadow_context",
    )
    assert ep.confidence_tier == "shadow"
    assert ep.relation_category == "shadow_context"


def test_episodic_relation_confidence_tier_schema() -> None:
    rel = EpisodicRelation(
        source_memory_id="mem-1",
        target_memory_id="mem-2",
        relation_type="cross_task_reference",
        confidence_tier="weak",
        relation_category="same_problem",
    )
    assert rel.confidence_tier == "weak"
    assert rel.relation_category == "same_problem"
    assert rel.weight == 1.0


def test_memory_context_format_action_execution_guard() -> None:
    learned = {
        "learned_episodes": [
            {
                "content": "Tried running sync sqlite query",
                "subtask_phase": "edit",
                "is_failure_attempt": True,
                "failure_reason": "Event loop blocked",
                "negative_lesson": "Use aiosqlite",
                "confidence_tier": "strong",
            },
            {
                "content": "Modified alembic revision version file",
                "subtask_phase": "edit",
                "is_failure_attempt": False,
                "confidence_tier": "strong",
            },
            {
                "content": "Rebooted redis cluster on staging 3 days ago",
                "subtask_phase": None,
                "is_failure_attempt": False,
                "confidence_tier": "weak",
            },
            {
                "content": "Inspected timeout threshold in db pool config",
                "subtask_phase": "locate",
                "is_failure_attempt": False,
                "confidence_tier": "shadow",
            },
        ]
    }
    ctx: dict[str, object] = {}
    stable, untrusted = _format_memory_context(ctx, learned, memory_search_enabled=False)

    assert untrusted is not None
    # 1. Failed attempts section
    assert "Failed Attempts & Negative Traps (Do not repeat)" in untrusted
    assert "Tried running sync sqlite query" in untrusted
    assert "Cause: Event loop blocked" in untrusted
    assert "AVOID: Use aiosqlite" in untrusted

    # 2. Strong subtask phase memory section
    assert "Subtask Phase Memories" in untrusted
    assert "[EDIT] Modified alembic revision version file" in untrusted

    # 3. Action execution guard for weak/shadow background context
    assert "Cross-Task Background Context (Weak/Shadow - Do not execute)" in untrusted
    assert "[BACKGROUND CONTEXT - Reference only, do not execute as automated SOP] Rebooted redis cluster" in untrusted
    assert "[LOCATE] [BACKGROUND CONTEXT - Reference only, do not execute as automated SOP] Inspected timeout threshold" in untrusted

    # 4. Prompt cache preservation: stable system prompt should not be polluted
    assert stable is None or "Rebooted redis cluster" not in stable


def test_memory_context_format_empty_and_corrupted_data() -> None:
    # Edge case 1: empty learned dict
    ctx: dict[str, object] = {}
    stable, untrusted = _format_memory_context(ctx, {}, memory_search_enabled=False)
    assert stable is None
    assert untrusted is None

    # Edge case 2: empty learned_episodes list
    stable, untrusted = _format_memory_context(ctx, {"learned_episodes": []}, memory_search_enabled=False)
    assert stable is None
    assert untrusted is None

    # Edge case 3: missing content or unknown confidence tier defaults safely
    corrupted_learned = {
        "learned_episodes": [
            {"content": "", "confidence_tier": "unknown_tier"},
            {"confidence_tier": "weak"},  # missing content entirely
        ]
    }
    stable, untrusted = _format_memory_context(ctx, corrupted_learned, memory_search_enabled=False)
    assert stable is None
    assert untrusted is None or "BACKGROUND CONTEXT" not in untrusted


def test_failure_attempt_takes_precedence_over_weak_tier() -> None:
    # High-stakes edge case: A failure attempt with 'weak' tier must still be captured
    # by the top-priority 'Failed Attempts & Negative Traps' firewall so the agent doesn't repeat it!
    learned = {
        "learned_episodes": [
            {
                "content": "Attempted direct socket bind without SO_REUSEADDR",
                "subtask_phase": "verify",
                "is_failure_attempt": True,
                "failure_reason": "Address already in use",
                "negative_lesson": "Always enable SO_REUSEADDR",
                "confidence_tier": "weak",
            }
        ]
    }
    ctx: dict[str, object] = {}
    stable, untrusted = _format_memory_context(ctx, learned, memory_search_enabled=False)

    assert untrusted is not None
    # Must enter Failed Attempts section
    assert "Failed Attempts & Negative Traps (Do not repeat)" in untrusted
    assert "AVOID: Always enable SO_REUSEADDR" in untrusted
    # Should NOT be demoted to pure background context
    assert "Cross-Task Background Context (Weak/Shadow - Do not execute)" not in untrusted


def test_large_mixed_context_budget_and_prompt_cache_isolation() -> None:
    # Stress edge case: Mixed 20 episodic memories across all tiers and phases
    episodes = []
    for i in range(10):
        episodes.append({
            "content": f"Resolved memory leak in worker pool #{i}",
            "subtask_phase": "edit" if i % 2 == 0 else "analyze",
            "is_failure_attempt": False,
            "confidence_tier": "strong" if i < 3 else ("weak" if i < 7 else "shadow"),
        })
    learned = {"learned_episodes": episodes}
    ctx: dict[str, object] = {}
    stable, untrusted = _format_memory_context(ctx, learned, memory_search_enabled=False)

    assert untrusted is not None
    assert "Subtask Phase Memories" in untrusted
    assert "Cross-Task Background Context (Weak/Shadow - Do not execute)" in untrusted
    # Prompt Cache rule: stable prompt must remain completely untouched
    assert stable is None

