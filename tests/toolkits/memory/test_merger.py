"""Unit and integration tests for DeterministicThreeStateMerger and ConfidenceEvolutionEngine."""

from datetime import UTC, datetime, timedelta

from myrm_agent_harness.toolkits.memory.strategies.distillation_guards import (
    EvidenceReference,
)
from myrm_agent_harness.toolkits.memory.strategies.merger import (
    ConfidenceEvolutionEngine,
    ConflictItem,
    DeterministicThreeStateMerger,
    MergeState,
)
from myrm_agent_harness.toolkits.memory.types import SemanticMemory


def test_user_override_lock_protects_existing_memory() -> None:
    """Human user-locked memory must be strictly protected against automated overwrites."""
    merger = DeterministicThreeStateMerger()
    locked_mem = SemanticMemory(
        content="禁止在生产数据库直接运行 DROP TABLE 操作",
        confidence=1.0,
        is_user_locked=True,
    )
    candidate = "测试时可以允许临时 drop table 重建"

    decision = merger.evaluate(locked_mem, candidate)
    assert decision.state == MergeState.USER_OVERRIDE_PROTECTED
    assert decision.merged_content == locked_mem.content
    assert "locked by explicit human override" in decision.reason


def test_exact_normalized_confirm_increases_confidence() -> None:
    """Identical or normalized duplicate corroborates fact, bumping confidence by +0.05."""
    merger = DeterministicThreeStateMerger()
    existing_ev = EvidenceReference(source_id="chat-1", message_id="msg-1", quote_snippet="我喜欢用 TypeScript")
    cand_ev = EvidenceReference(source_id="chat-1", message_id="msg-2", quote_snippet="写代码必须是 TypeScript")

    existing_mem = SemanticMemory(
        content="用户主力开发语言是 TypeScript",
        confidence=0.85,
        evidence=[existing_ev],
    )
    candidate = " 用户主力开发语言是 TypeScript  "

    decision = merger.evaluate(existing_mem, candidate, candidate_evidence=[cand_ev])
    assert decision.state == MergeState.CONFIRM
    assert decision.updated_confidence == 0.90
    assert len(decision.merged_evidence) == 2


def test_facet_conflict_location_detected() -> None:
    """Mutually exclusive values in a known single-valued slot must trigger Conflict with dual decay."""
    merger = DeterministicThreeStateMerger()
    existing_mem = SemanticMemory(
        content="用户常住在深圳南山区",
        confidence=0.85,
    )
    candidate = "用户已经搬到西雅图办公生活了"

    decision = merger.evaluate(existing_mem, candidate)
    assert decision.state == MergeState.CONFLICT
    assert decision.updated_confidence == 0.35
    assert decision.candidate_confidence == 0.35
    assert decision.conflict_item is not None
    assert decision.conflict_item.facet == "location"
    assert decision.conflict_item.existing_memory_id == existing_mem.id
    assert decision.conflict_item.candidate_content == candidate


def test_facet_conflict_runtime_detected() -> None:
    """Runtime conflict (Bun vs Node) must decay both confidences."""
    merger = DeterministicThreeStateMerger()
    existing_mem = SemanticMemory(
        content="项目必须使用 node 运行",
        confidence=0.90,
    )
    candidate = "项目必须使用 bun 运行"

    decision = merger.evaluate(existing_mem, candidate)
    assert decision.state == MergeState.CONFLICT
    assert decision.conflict_item is not None
    assert decision.conflict_item.facet == "runtime"


def test_negation_polarity_inversion_conflict() -> None:
    """Explicit negation vs affirmation contradiction triggers conflict."""
    merger = DeterministicThreeStateMerger()
    existing_mem = SemanticMemory(
        content="用户喜欢吃辣",
        confidence=0.80,
    )
    candidate = "用户不喜欢吃辣"

    decision = merger.evaluate(existing_mem, candidate)
    assert decision.state == MergeState.CONFLICT
    assert decision.conflict_item is not None
    assert decision.conflict_item.facet == "polarity_inversion"


def test_supplement_content_merging() -> None:
    """Incremental detail expansion is merged into the existing fact as a supplement."""
    merger = DeterministicThreeStateMerger()
    existing_mem = SemanticMemory(
        content="用户是全栈工程师",
        confidence=0.85,
    )
    candidate = "用户是全栈工程师，擅长 FastAPI 与 Next.js"

    decision = merger.evaluate(existing_mem, candidate)
    assert decision.state == MergeState.SUPPLEMENT
    assert decision.merged_content == "用户是全栈工程师，擅长 FastAPI 与 Next.js"
    assert decision.updated_confidence == 0.85


def test_confidence_evolution_max_cap() -> None:
    """Repeated corroboration caps confidence at 0.98 without runaway growth."""
    conf = 0.95
    conf = ConfidenceEvolutionEngine.evolve_on_confirm(conf)
    assert conf == 0.98
    conf = ConfidenceEvolutionEngine.evolve_on_confirm(conf)
    assert conf == 0.98


def test_temporal_reconciliation_self_healing() -> None:
    """Conflict with >= 3 activations within 14-day window triggers automatic reconciliation."""
    now = datetime.now(UTC)
    conflict = ConflictItem(
        existing_memory_id="mem-1",
        candidate_content="用户常驻西雅图",
        existing_content="用户常驻深圳",
        detected_at=now - timedelta(days=5),
        activation_count=3,
    )
    assert ConfidenceEvolutionEngine.check_temporal_reconciliation(conflict, current_time=now) is True

    # If activation count < 3, no auto-reconciliation
    conflict_pending = ConflictItem(
        existing_memory_id="mem-1",
        candidate_content="用户常驻西雅图",
        existing_content="用户常驻深圳",
        detected_at=now - timedelta(days=5),
        activation_count=2,
    )
    assert ConfidenceEvolutionEngine.check_temporal_reconciliation(conflict_pending, current_time=now) is False

    # If outside 14 days window, does not auto-reconcile
    conflict_expired = ConflictItem(
        existing_memory_id="mem-1",
        candidate_content="用户常驻西雅图",
        existing_content="用户常驻深圳",
        detected_at=now - timedelta(days=15),
        activation_count=5,
    )
    assert ConfidenceEvolutionEngine.check_temporal_reconciliation(conflict_expired, current_time=now) is False


def test_vector_similarity_thresholds() -> None:
    """Cosine similarity thresholds guide fallback decisions."""
    merger = DeterministicThreeStateMerger()
    existing_mem = SemanticMemory(
        content="用户爱好马拉松长跑",
        confidence=0.80,
    )

    # High similarity (>0.94) -> CONFIRM
    res_high = merger.evaluate(existing_mem, "用户平时喜爱长距离马拉松跑步", similarity=0.96)
    assert res_high.state == MergeState.CONFIRM
    assert res_high.updated_confidence == 0.85

    # Moderate similarity (0.72 - 0.94) -> CONFLICT
    res_mod = merger.evaluate(existing_mem, "用户偶尔参加跑步运动", similarity=0.82)
    assert res_mod.state == MergeState.CONFLICT

    # Low similarity (<0.72) -> NEW
    res_low = merger.evaluate(existing_mem, "用户喜欢阅读科幻小说", similarity=0.45)
    assert res_low.state == MergeState.NEW
