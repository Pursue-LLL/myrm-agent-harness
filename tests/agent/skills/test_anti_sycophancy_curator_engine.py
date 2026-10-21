# ============================================================================
# Unit Tests for AntiSycophancyAdversarialReviewAndSelfDismantlingCurator (Item 149)
# Verifies sycophancy detection, adversarial critic personas, in-context RL exemplars,
# and transparent self-dismantling memory/skill curation sweeps.
# ============================================================================


from myrm_agent_harness.agent.skills.curator import (
    AdversarialCriticRole,
    AntiSycophancyAdversarialEngine,
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

