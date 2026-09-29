"""Unit and integration tests for DeterministicThreeStateMerger and ConfidenceEvolutionEngine."""

from datetime import UTC, datetime, timedelta

import pytest

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


def test_pinned_memory_also_triggers_user_override_protection() -> None:
    """A pinned memory must reach USER_OVERRIDE_PROTECTED, not only a user-locked one."""
    merger = DeterministicThreeStateMerger()
    pinned_mem = SemanticMemory(
        content="禁止在生产数据库直接运行 DROP TABLE 操作",
        confidence=1.0,
        pinned=True,
    )

    decision = merger.evaluate(pinned_mem, "测试时可以允许临时 drop table 重建")

    assert decision.state == MergeState.USER_OVERRIDE_PROTECTED
    assert decision.merged_content == pinned_mem.content


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


def test_facet_conflict_same_trigger_different_value() -> None:
    """A bare trigger on both sides still conflicts when only the value changes."""
    merger = DeterministicThreeStateMerger()
    existing_mem = SemanticMemory(content="用户工作地在杭州", confidence=0.85)

    decision = merger.evaluate(existing_mem, "用户工作地在上海")

    assert decision.state == MergeState.CONFLICT
    assert decision.conflict_item is not None
    assert decision.conflict_item.facet == "location"
    assert decision.updated_confidence == 0.35


def test_facet_conflict_ignores_identical_value() -> None:
    """Restating the same value must not be treated as a contradiction."""
    merger = DeterministicThreeStateMerger()
    existing_mem = SemanticMemory(content="用户工作地在杭州", confidence=0.85)

    decision = merger.evaluate(existing_mem, "用户工作地在杭州")

    assert decision.state != MergeState.CONFLICT


def test_facet_conflict_ignores_subsumed_value() -> None:
    """A more specific phrasing of the same value is not a contradiction."""
    merger = DeterministicThreeStateMerger()
    existing_mem = SemanticMemory(content="用户位于北京", confidence=0.85)

    decision = merger.evaluate(existing_mem, "用户位于北京市海淀区")

    assert decision.state != MergeState.CONFLICT


def test_facet_conflict_handles_mixed_case_pattern() -> None:
    """A facet pattern with capitals still yields a value from lowercased text."""
    merger = DeterministicThreeStateMerger()
    values = merger._extract_facet_values("使用 macos 开发", "macOS")

    assert values == frozenset({"开发"})


def test_facet_conflict_scans_every_occurrence() -> None:
    """A memory that revised itself exposes all its values, not just the first."""
    merger = DeterministicThreeStateMerger()
    trigger = "工作" + "在" + "地"
    text = trigger + "杭州，" + trigger + "上海"

    assert merger._extract_facet_values(text, trigger) == frozenset({"杭州", "上海"})


def test_facet_conflict_ignores_wording_around_the_choice() -> None:
    """A decision reversal is caught however the user phrased it."""
    merger = DeterministicThreeStateMerger()
    existing_mem = SemanticMemory(content="我装了 Cursor", confidence=0.9)

    decision = merger.evaluate(existing_mem, "我装了 Emacs")

    assert decision.state == MergeState.CONFLICT
    assert decision.conflict_item is not None
    assert decision.conflict_item.facet == "editor_ide"


def test_facet_conflict_covers_stack_decisions() -> None:
    """Reversing a stack decision — the case that makes an agent repeat itself."""
    merger = DeterministicThreeStateMerger()
    cases = [
        ("项目缓存使用 Redis", "项目缓存改用 Memcached", "cache_store"),
        ("数据库用 PostgreSQL", "数据库换成 MySQL", "database"),
        ("后端用 SQLAlchemy", "后端改用 Prisma", "orm"),
        ("前端用 React", "前端改成 Vue", "frontend_framework"),
    ]
    for existing, candidate, facet in cases:
        decision = merger.evaluate(SemanticMemory(content=existing, confidence=0.9), candidate)
        assert decision.state == MergeState.CONFLICT, existing
        assert decision.conflict_item is not None
        assert decision.conflict_item.facet == facet, existing


def test_facet_conflict_ignores_text_without_a_shared_facet() -> None:
    """Two unrelated technologies in one sentence are not a contradiction."""
    merger = DeterministicThreeStateMerger()
    existing_mem = SemanticMemory(content="项目缓存使用 Redis", confidence=0.9)

    decision = merger.evaluate(existing_mem, "数据库使用 PostgreSQL")

    assert decision.state != MergeState.CONFLICT


def test_facet_conflict_requires_a_shared_subject() -> None:
    """Naming a competing tool in unrelated sentences is not a contradiction.

    A stray mention of another framework decays both memories, and decayed
    confidence does not recover on its own, so an unrelated pair stays silent.
    """
    merger = DeterministicThreeStateMerger()
    existing_mem = SemanticMemory(content="我不太懂 react", confidence=0.9)

    decision = merger.evaluate(existing_mem, "他说 solid 很有意思")

    assert decision.state != MergeState.CONFLICT


def test_facet_value_entry_does_not_absorb_following_words() -> None:
    """A bare value stands for itself; the words after it are not part of it."""
    merger = DeterministicThreeStateMerger()
    values = merger._facet_values("项目必须使用 node 运行", merger._MUTUALLY_EXCLUSIVE_FACETS["runtime"])

    assert values == frozenset({"node"})


def test_facet_value_extraction_is_bounded() -> None:
    """Trigger-dense text cannot make value extraction scan without limit."""
    merger = DeterministicThreeStateMerger()
    trigger = "工作" + "在" + "地"
    dense = (trigger + "杭州，") * 20_000

    values = merger._extract_facet_values(dense, trigger)

    assert values == frozenset({"杭州"})
    assert len(dense) > 100_000


def test_facet_conflict_stays_silent_when_new_claim_is_narrower() -> None:
    """Naming an extra option without a switch marker is detail, not a reversal."""
    merger = DeterministicThreeStateMerger()
    stored = "项目缓存使用 Redis，同时用 Memcached 做二级缓存"
    decision = merger.evaluate(SemanticMemory(content=stored, confidence=0.9), "项目缓存使用 Memcached")
    assert decision.state != MergeState.CONFLICT


def test_switch_to_new_value_conflicts_with_the_replaced_one() -> None:
    """Real extraction writes "不用 Redis，改用 Memcached" as a single memory.

    Both names appear in one sentence, so the switch marker has to scope the
    assertion to Memcached; otherwise the shared "redis" hides the reversal.
    """
    merger = DeterministicThreeStateMerger()
    switch = "项目缓存不再使用 Redis，改用 Memcached，原因是运维团队更熟"

    decision = merger.evaluate(SemanticMemory(content="项目缓存使用 Redis", confidence=0.9), switch)
    assert decision.state == MergeState.CONFLICT
    assert decision.conflict_item is not None
    assert decision.conflict_item.facet == "cache_store"

    # Agreeing with the choice the switch lands on is a duplicate, not a conflict.
    assert (
        merger.evaluate(SemanticMemory(content="项目缓存使用 Memcached", confidence=0.9), switch).state
        != MergeState.CONFLICT
    )


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


@pytest.mark.parametrize(
    "reversal",
    [
        "自2026-09-29起，项目缓存层不再使用 Redis，统一改用 Memcached；原因是运维团队对 Memcached 更熟悉。",
        "项目缓存层已确定不再使用 Redis，必须改用 Memcached。",
        "项目选择 Memcached 而非 Redis 的原因是运维团队更熟悉。",
    ],
    ids=["switch-after-rejection", "switch-only", "exclusion"],
)
def test_real_model_wording_yields_a_replacement_target(reversal: str) -> None:
    """Extraction states a reversal in its own words, and the target must be found.

    `_facet_values` already narrows to the surviving value, so re-comparing the two
    could never tell a replacement from a plain statement; the marker firing is the
    only signal. Pinning the real wordings keeps that signal from regressing.
    """
    merger = DeterministicThreeStateMerger()
    decision = merger.evaluate(
        SemanticMemory(content="用户已确定其项目技术方案采用 Redis。", confidence=0.9),
        reversal,
        similarity=0.8,
    )

    assert decision.state == MergeState.CONFLICT
    assert decision.conflict_item is not None
    assert decision.conflict_item.facet == "cache_store"
    assert decision.candidate_supersedes is True, merger.replacement_targets_by_facet(reversal)
