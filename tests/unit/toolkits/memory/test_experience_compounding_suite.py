"""[POS]: tests/unit/toolkits/memory/test_experience_compounding_suite.py
[INPUT]: None.
[OUTPUT]: Comprehensive unit tests for Item 136 ExperienceCompoundingAndKnowledgeCondensationSuite.
"""

from __future__ import annotations

import time

from myrm_agent_harness.toolkits.memory.experience_compounding import (
    CompoundedExperienceItem,
    ExperienceCompoundingSuite,
    ExperienceItemState,
    FrequencyCompoundingEngine,
    KnowledgeCondensationEngine,
    ObsoleteContextAnnealingGovernor,
    compute_compounded_weight,
)


def test_frequency_compounding_growth_and_saturation() -> None:
    """Verify logarithmic growth and bounded saturation threshold of compounding weights."""
    engine = FrequencyCompoundingEngine(max_multiplier=2.5)
    item = CompoundedExperienceItem(
        item_id="exp-1",
        content="喜欢使用 2 空格紧凑排版",
        topic="coding_style",
        base_weight=1.0,
    )

    # Initial state
    assert item.compounded_weight == 1.0

    # 1. Repeated adoptions should increase weight monotonically
    weights: list[float] = []
    for _ in range(5):
        w = engine.reinforce(item, adopted=True)
        weights.append(w)

    for i in range(len(weights) - 1):
        assert weights[i] <= weights[i + 1]

    # 2. Extreme adoptions (e.g. 500 times) should saturate at max_multiplier (2.5)
    item_extreme = CompoundedExperienceItem(
        item_id="exp-extreme",
        content="核心公理规则",
        topic="axioms",
        base_weight=1.0,
    )
    for _ in range(300):
        engine.reinforce(item_extreme, adopted=True)

    assert item_extreme.compounded_weight <= 2.5
    assert item_extreme.compounded_weight == 2.5

    # Pure function evaluation
    pure_w = compute_compounded_weight(base_weight=2.0, adoption_count=100, max_multiplier=2.5)
    assert pure_w == 5.0


def test_dynamic_half_life_extension() -> None:
    """Verify that repeated verification dynamically extends memory half-life."""
    engine = FrequencyCompoundingEngine(max_half_life_days=180.0)
    item = CompoundedExperienceItem(
        item_id="exp-axiom",
        content="严禁使用 Any 类型注解",
        topic="code_quality",
        base_weight=1.0,
        half_life_days=14.0,
    )

    assert item.half_life_days == 14.0

    for _ in range(10):
        engine.reinforce(item, adopted=True)

    # Half life should be extended beyond initial 14 days
    assert item.half_life_days > 14.0
    assert item.half_life_days <= 180.0


def test_knowledge_condensation_synthesis_and_lineage() -> None:
    """Verify that fragmented notes are synthesized into Golden Rules with lineage tracking."""
    condensation = KnowledgeCondensationEngine(min_cluster_size=2, similarity_threshold=0.20)
    fragments = [
        CompoundedExperienceItem(
            item_id="frag-1",
            content="代码排版风格偏好 2 空格缩进排版",
            topic="code_format",
            base_weight=1.2,
        ),
        CompoundedExperienceItem(
            item_id="frag-2",
            content="函数排版风格偏好紧凑排版行宽限制 100",
            topic="code_format",
            base_weight=1.3,
        ),
        CompoundedExperienceItem(
            item_id="frag-3",
            content="喜欢周末早上跑步五公里",
            topic="lifestyle",
            base_weight=1.0,
        ),
    ]

    rules, report = condensation.condense(fragments)

    assert len(rules) == 1
    assert report.rules_generated == 1
    assert report.fragments_archived == 2
    assert report.compression_ratio > 0.0

    rule = rules[0]
    assert rule.topic == "code_format"
    assert "frag-1" in rule.source_fragment_ids
    assert "frag-2" in rule.source_fragment_ids

    # Check non-destructive state update of original fragments
    f1 = next(f for f in fragments if f.item_id == "frag-1")
    f2 = next(f for f in fragments if f.item_id == "frag-2")
    f3 = next(f for f in fragments if f.item_id == "frag-3")

    assert f1.state == ExperienceItemState.CONDENSED_ARCHIVED
    assert f2.state == ExperienceItemState.CONDENSED_ARCHIVED
    assert f3.state == ExperienceItemState.ACTIVE  # Unrelated fragment remains active


def test_golden_rule_decondensation_rollback() -> None:
    """Verify that Golden Rules can be rolled back to reactivate original fragments."""
    condensation = KnowledgeCondensationEngine(min_cluster_size=2, similarity_threshold=0.20)
    fragments = [
        CompoundedExperienceItem(
            item_id="frag-a",
            content="前端组件优先使用 TailwindCSS 样式",
            topic="frontend",
            base_weight=1.0,
        ),
        CompoundedExperienceItem(
            item_id="frag-b",
            content="前端界面优先使用 Flexbox 弹性布局样式",
            topic="frontend",
            base_weight=1.0,
        ),
    ]

    rules, _ = condensation.condense(fragments)
    assert len(rules) == 1
    rule_id = rules[0].rule_id

    # Rollback decondensation
    reactivated = condensation.decondense(rule_id, rules, fragments)
    assert len(rules) == 0
    assert len(reactivated) == 2
    assert all(f.state == ExperienceItemState.ACTIVE for f in reactivated)


def test_obsolete_context_annealing_and_active_lease_protection() -> None:
    """Verify active lease exemption and exponential decay into cold tier."""
    governor = ObsoleteContextAnnealingGovernor(cold_tier_threshold=0.20, temporary_half_life_days=2.0)
    now = time.time()
    past_10_days = now - 10 * 86400.0

    pinned_item = CompoundedExperienceItem(
        item_id="it-pinned",
        content="长期有效的组织架构与部署模式",
        topic="infra",
        base_weight=1.5,
        compounded_weight=1.5,
        last_adopted_at=past_10_days,
        is_pinned=True,  # Active lease
    )

    temporary_old_item = CompoundedExperienceItem(
        item_id="it-temp-old",
        content="排查临时调试端口 8089 端口占用错误",
        topic="debug",
        base_weight=1.0,
        compounded_weight=1.0,
        last_adopted_at=past_10_days,
        is_temporary=True,  # No lease, short half life
    )

    items = [pinned_item, temporary_old_item]
    report = governor.apply_annealing(items, current_time=now)

    assert report.inspected_count == 2
    assert report.active_lease_exempt_count == 1
    assert report.cold_tiered_count == 1

    # Pinned item should remain ACTIVE with unchanged weight
    assert pinned_item.state == ExperienceItemState.ACTIVE
    assert pinned_item.compounded_weight == 1.5

    # Temporary old item should be demoted to COLD_TIERED
    assert temporary_old_item.state == ExperienceItemState.COLD_TIERED
    assert temporary_old_item.compounded_weight < 0.20


def test_facade_suite_end_to_end() -> None:
    """Verify turnkey ExperienceCompoundingSuite facade operations."""
    suite = ExperienceCompoundingSuite()

    # 1. Add items
    it1 = suite.add_item("偏好 Python 类型注解规范与 mypy", topic="typing", base_weight=1.0)
    suite.add_item("偏好 Python 严格类型注解与强契约", topic="typing", base_weight=1.0)
    suite.add_item("一次性脚本排查记录", topic="debug", is_temporary=True)

    # 2. Reinforce
    new_w = suite.reinforce(it1.item_id, adopted=True)
    assert new_w > 1.0

    # 3. Condense
    rules, cond_report = suite.condense()
    assert len(rules) == 1
    assert cond_report.rules_generated == 1
    assert len(suite.list_golden_rules()) == 1

    # 4. Stats
    stats = suite.get_stats()
    assert stats["total_items"] == 3
    assert stats["condensed_items"] == 2
    assert stats["golden_rules_count"] == 1
