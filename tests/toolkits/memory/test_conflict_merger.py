"""Tests for deterministic three-state conflict merge and confidence evolution."""

from datetime import UTC, datetime, timedelta

import pytest
from myrm_agent_harness.toolkits.memory.strategies.conflict_merger import (
    AUTO_UNFREEZE_CONFIRM_COUNT,
    AUTO_UNFREEZE_DAYS,
    CONFIDENCE_PENALTY_CONFLICT,
    CONFIDENCE_STEP_CONFIRM,
    MAX_CONFIDENCE_CAP,
    ConflictDetail,
    MergeAction,
    MergeRelation,
    MergeResult,
    classify_relation,
    merge_evidence_references,
    merge_memory_candidate,
)
from myrm_agent_harness.toolkits.memory.strategies.distillation_guards import (
    EvidenceReference,
)
from myrm_agent_harness.toolkits.memory.strategies.forgetting import (
    ForgettingConfig,
    ForgettingStrategy,
)
from myrm_agent_harness.toolkits.memory.types import (
    ProceduralMemory,
    SemanticMemory,
)


def test_classify_relation_confirm_and_supplement_and_conflict() -> None:
    # Scalar strings
    assert classify_relation("bun", "bun") == MergeRelation.CONFIRM
    assert classify_relation("bun", "pnpm") == MergeRelation.CONFLICT

    # Lists (superset = supplement, disjoint/modified = conflict)
    assert classify_relation(["python", "pytest"], ["python", "pytest", "ruff"]) == MergeRelation.SUPPLEMENT
    assert classify_relation(["python", "pytest"], ["python", "unittest"]) == MergeRelation.CONFLICT

    # Dictionaries
    assert classify_relation({"env": "prod"}, {"env": "prod"}) == MergeRelation.CONFIRM
    assert classify_relation({"env": "prod"}, {"env": "prod", "region": "us-east"}) == MergeRelation.SUPPLEMENT
    assert classify_relation({"env": "prod"}, {"env": "staging"}) == MergeRelation.CONFLICT


def test_merge_evidence_references_deduplication_and_order() -> None:
    ev1 = EvidenceReference(source_id="chat_1", message_id="m1", quote_snippet="quote A")
    ev2 = EvidenceReference(source_id="chat_2", message_id="m2", quote_snippet="quote B")
    ev1_dup = EvidenceReference(source_id="chat_1", message_id="m1", quote_snippet="quote A")

    merged = merge_evidence_references(existing=[ev1], incoming=[ev2, ev1_dup])
    assert len(merged) == 2
    # Incoming should be placed first
    assert merged[0].message_id == "m2"
    assert merged[1].message_id == "m1"


def test_merge_first_time_insert() -> None:
    ev = EvidenceReference(source_id="chat_init", message_id="m_init", quote_snippet="init fact")
    candidate = SemanticMemory(
        user_id="user_123",
        content="User prefers dark theme",
        confidence=0.85,
    )
    candidate.evidence = [ev]

    result = merge_memory_candidate(existing=None, candidate=candidate)
    assert result.action == MergeAction.INSERT
    assert result.relation == MergeRelation.INDEPENDENT
    assert result.confidence == 0.85
    assert len(result.evidence) == 1
    assert result.evidence[0].source_id == "chat_init"


def test_merge_confirm_bumps_confidence_and_merges_evidence() -> None:
    ev_old = EvidenceReference(source_id="chat_1", message_id="m1", quote_snippet="I use bun")
    existing = SemanticMemory(
        user_id="user_123",
        content="Preferred package manager is Bun",
        confidence=0.90,
    )
    existing.evidence = [ev_old]

    ev_new = EvidenceReference(source_id="chat_2", message_id="m2", quote_snippet="Always run bun install")
    candidate = SemanticMemory(
        user_id="user_123",
        content="Preferred package manager is Bun",
        confidence=0.80,
    )
    candidate.evidence = [ev_new]

    result = merge_memory_candidate(existing=existing, candidate=candidate)
    assert result.action == MergeAction.UPDATE
    assert result.relation == MergeRelation.CONFIRM
    assert result.confidence == pytest.approx(0.95)
    assert len(result.evidence) == 2
    assert result.evidence[0].message_id == "m2"


def test_merge_confidence_caps_at_maximum() -> None:
    existing = SemanticMemory(
        user_id="user_123",
        content="User role is Senior Architect",
        confidence=0.96,
    )
    candidate = SemanticMemory(
        user_id="user_123",
        content="User role is Senior Architect",
        confidence=0.90,
    )
    result = merge_memory_candidate(existing=existing, candidate=candidate)
    assert result.confidence == MAX_CONFIDENCE_CAP


def test_merge_user_override_wins_hard_protection() -> None:
    # User locked memory
    existing = SemanticMemory(
        user_id="user_123",
        content="Deploy target is AWS EKS",
        confidence=1.0,
    )
    existing.is_user_locked = True

    # Assistant distillation tries to overwrite with Cloudflare Workers
    candidate = SemanticMemory(
        user_id="user_123",
        content="Deploy target is Cloudflare Workers",
        confidence=0.88,
    )

    result = merge_memory_candidate(
        existing=existing,
        candidate=candidate,
        candidate_source="assistant_distillation",
    )
    assert result.action == MergeAction.SKIP
    assert result.relation == MergeRelation.CONFLICT
    assert result.skip_reason == "user_override_wins"
    assert result.is_user_locked is True
    assert result.requires_governance is True
    assert result.conflict is not None
    assert "User Override Wins" in result.conflict.reason


def test_merge_conflict_penalizes_confidence_and_suspends_for_governance() -> None:
    existing = SemanticMemory(
        user_id="user_123",
        content="Preferred test runner is pytest",
        confidence=0.90,
    )
    candidate = SemanticMemory(
        user_id="user_123",
        content="Preferred test runner is vitest",
        confidence=0.85,
    )

    result = merge_memory_candidate(existing=existing, candidate=candidate)
    assert result.action == MergeAction.SUSPEND
    assert result.relation == MergeRelation.CONFLICT
    assert result.confidence == CONFIDENCE_PENALTY_CONFLICT
    assert result.requires_governance is True
    assert result.conflict is not None
    assert result.conflict.existing_value == "Preferred test runner is pytest"
    assert result.conflict.candidate_value == "Preferred test runner is vitest"


def test_procedural_memory_tri_state_handling() -> None:
    # Same trigger, different tool -> Conflict
    p_old = ProceduralMemory(
        user_id="user_123",
        content="When formatting code, run prettier",
        trigger="format_code",
        action="run code formatter",
        tool_name="prettier",
        confidence=0.90,
    )
    p_new_conflict = ProceduralMemory(
        user_id="user_123",
        content="When formatting code, run biome",
        trigger="format_code",
        action="run code formatter",
        tool_name="biome",
        confidence=0.85,
    )
    res_conflict = merge_memory_candidate(existing=p_old, candidate=p_new_conflict)
    assert res_conflict.relation == MergeRelation.CONFLICT
    assert res_conflict.action == MergeAction.SUSPEND

    # Same trigger, same tool, extended action -> Supplement
    p_supplement = ProceduralMemory(
        user_id="user_123",
        content="When formatting code, run prettier with --write",
        trigger="format_code",
        action="run code formatter with --write",
        tool_name="prettier",
        confidence=0.85,
    )
    res_supp = merge_memory_candidate(existing=p_old, candidate=p_supplement)
    assert res_supp.relation == MergeRelation.SUPPLEMENT
    assert res_supp.action == MergeAction.UPDATE


def test_auto_unfreeze_stale_conflict() -> None:
    now = datetime.now(UTC)
    old_time = now - timedelta(days=10)

    existing = SemanticMemory(
        user_id="user_123",
        content="Node runtime is v18",
        confidence=0.90,
    )
    existing.created_at = old_time

    # Candidate repeatedly confirmed (count >= 3)
    candidate = SemanticMemory(
        user_id="user_123",
        content="Node runtime is v22",
        confidence=0.95,
        metadata={"confirm_count": 4},
    )

    result = merge_memory_candidate(existing=existing, candidate=candidate, now=now)
    assert result.action == MergeAction.UPDATE
    assert result.relation == MergeRelation.SUPPLEMENT
    assert result.skip_reason == "auto_unfrozen_superseded"
    assert result.confidence == 0.95


def test_forgetting_strategy_immunizes_contested_conflicts() -> None:
    now = datetime.now(UTC)
    strategy = ForgettingStrategy(
        ForgettingConfig(
            min_retention_days=0,
            time_decay_half_life_days=1.0,
            retention_threshold=0.50,
        )
    )

    # Low-confidence aged memory without conflict tag gets forgotten
    mem_normal = SemanticMemory(
        user_id="user_123",
        content="Temporary scratchpad note",
        confidence=0.20,
        importance=0.10,
        user_rating=0.0,
    )
    mem_normal.created_at = now - timedelta(days=10)
    score_normal = strategy.calculate_retention_score(mem_normal)
    assert score_normal.should_forget is True

    # Memory tagged with conflict_status="conflicted" is immunized from garbage collection
    mem_conflicted = SemanticMemory(
        user_id="user_123",
        content="Contested statement awaiting user review",
        confidence=0.20,
        importance=0.10,
        user_rating=0.0,
        metadata={"conflict_status": "conflicted"},
    )
    mem_conflicted.created_at = now - timedelta(days=10)
    score_conflicted = strategy.calculate_retention_score(mem_conflicted)
    assert score_conflicted.should_forget is False
    assert "Protected: contested memory awaiting human governance" in score_conflicted.reason
