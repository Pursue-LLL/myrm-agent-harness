# ============================================================================
# Unit Tests for AntiSycophancyAdversarialReviewAndSelfDismantlingCurator (Item 149)
# Verifies sycophancy detection, adversarial critic personas, in-context RL exemplars,
# and transparent self-dismantling memory/skill curation sweeps.
# ============================================================================

import time

from myrm_agent_harness.agent.skills.curator import (
    AdversarialCriticRole,
    AntiSycophancyAdversarialEngine,
    CuratedAction,
    CuratorCustomRules,
    SelfDismantlingCuratorEngine,
)


def test_detect_sycophancy_signals() -> None:
    """Verifies detection of subservient flattering phrases in Chinese and English."""
    engine = AntiSycophancyAdversarialEngine()

    flattering_cn = "您说得太对了！您这个方案简直完美无瑕，我们立即按照您的英明指示照办。"
    signals_cn = engine.detect_sycophancy_signals(flattering_cn)
    assert len(signals_cn) >= 2
    assert any("您说得太对" in s for s in signals_cn)
    assert any("完美无瑕" in s for s in signals_cn)

    flattering_en = "You are completely right! That is a brilliant idea, let's proceed."
    signals_en = engine.detect_sycophancy_signals(flattering_en)
    assert len(signals_en) >= 2
    assert any("completely right" in s.lower() for s in signals_en)

    neutral_response = "经过第一性原理分析，该方案具备可行性，但建议针对高并发场景增加熔断限流保护。"
    assert engine.detect_sycophancy_signals(neutral_response) == []


def test_review_and_critique_personas() -> None:
    """Verifies that different critic roles generate specialized attack vectors and RL exemplars."""
    engine = AntiSycophancyAdversarialEngine()

    # Architect Critic
    arch_review = engine.review_and_critique(
        user_prompt="我们把所有业务逻辑都写在单个大文件里以提高开发速度。",
        assistant_response="您说得太对了，这样改确实最省事。",
        role=AdversarialCriticRole.ARCHITECT_CRITIC,
    )
    assert arch_review.is_sycophantic
    assert arch_review.critic_role == AdversarialCriticRole.ARCHITECT_CRITIC
    assert len(arch_review.potential_pitfalls) >= 2
    assert "<in_context_rl_exemplar role=\"architect_critic\">" in arch_review.in_context_rl_exemplar
    assert "架构批判者审查" in arch_review.critique_summary

    # Security Redteam
    sec_review = engine.review_and_critique(
        user_prompt="直接用 eval 执行用户传入的表达式。",
        assistant_response="方案没问题，这就写代码。",
        role=AdversarialCriticRole.SECURITY_REDTEAM,
    )
    assert sec_review.critic_role == AdversarialCriticRole.SECURITY_REDTEAM
    assert any("安全" in p or "输入" in p or "越权" in p for p in sec_review.potential_pitfalls)


def test_self_dismantling_curator_sweep() -> None:
    """Tests automatic pruning, distillation, and retention across a batch of memories/skills."""
    curator = SelfDismantlingCuratorEngine()
    now = time.time()

    items = [
        # Fresh, unique item -> RETAIN
        {
            "id": "mem-1",
            "type": "memory",
            "content": "PostgreSQL 16 connection pooling config with pgbouncer port 6432",
            "created_at": now - 3600,
        },
        # Redundant duplicate item -> DISTILL
        {
            "id": "mem-2",
            "type": "memory",
            "content": "PostgreSQL connection pooling configuration with pgbouncer on port 6432",
            "created_at": now - 7200,
        },
        # Very stale item (60 days old) -> PRUNE
        {
            "id": "mem-3",
            "type": "skill",
            "content": "Deprecated temporary quickfix for legacy python 2.7 build error",
            "created_at": now - (60 * 86400),
        },
    ]

    rules = CuratorCustomRules(
        user_guidelines=["数据库优化与连接池架构"],
        max_staleness_days=30,
        dedup_similarity_threshold=0.70,
        prune_threshold=0.40,
    )

    report = curator.curate_knowledge_and_skills(items=items, custom_rules=rules)

    assert report.scanned_items_count == 3
    assert report.retained_count >= 1
    assert report.distilled_count >= 1
    assert report.pruned_count >= 1

    # Check verdicts
    v_stale = next(v for v in report.verdicts if v.item_id == "mem-3")
    assert v_stale.action == CuratedAction.PRUNE

    v_dup = next(v for v in report.verdicts if v.item_id == "mem-2")
    assert v_dup.action == CuratedAction.DISTILL
    assert v_dup.distilled_content is not None
    assert "提纯核心" in v_dup.distilled_content

    assert "Hermes Curator 自我蒸馏策展报告" in report.summary_markdown
