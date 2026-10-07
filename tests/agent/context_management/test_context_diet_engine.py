"""常设全局背景按需技能化、开局底噪透视与纯净创造力节食套件单元测试。

[INPUT]
- ContextDietEngine, ContextComponentKind, ContextDietConfig, ContextDietBudgetBill, DistilledSkillCard

[OUTPUT]
- 自动化验证底噪账单分解、TTFT首字延迟预估、长篇人设技能化蒸馏与纯净思维模式转换

[POS]
- 位于 tests/agent/context_management/test_context_diet_engine.py
"""

from myrm_agent_harness.agent.context_management.context_diet import (
    ContextComponentKind,
    ContextDietBudgetBill,
    ContextDietConfig,
    ContextDietEngine,
    DistilledSkillCard,
)


def test_audit_opening_budget_breakdown_and_ttft() -> None:
    """测试开局底噪各要素分解、Token 占比与 TTFT 首字延迟预估。"""
    config = ContextDietConfig(
        total_window_capacity=100_000,
        ttft_ms_per_thousand_tokens=100.0,
        token_char_ratio=4.0,
    )
    engine = ContextDietEngine(config)

    components = {
        ContextComponentKind.SYSTEM_PROMPT: "A" * 800,  # 200 tokens
        ContextComponentKind.TOOL_SCHEMAS: "B" * 1200,  # 300 tokens
        ContextComponentKind.SKILLS_INDEX: "C" * 400,  # 100 tokens
        ContextComponentKind.MEMORY_BRIEF: "D" * 400,  # 100 tokens
        ContextComponentKind.ENVIRONMENT_FACTS: "E" * 400,  # 100 tokens
        ContextComponentKind.STATIC_PERSONA: "F" * 400,  # 100 tokens
    }
    # 总计 900 tokens

    bill: ContextDietBudgetBill = engine.audit_opening_budget(components)

    assert bill.total_opening_tokens == 900
    assert bill.total_window_capacity == 100_000
    assert bill.opening_overhead_percent == 0.9  # 900 / 100000 * 100%
    assert bill.estimated_ttft_ms == 90.0  # 900 / 1000 * 100ms
    assert len(bill.components) == len(ContextComponentKind)

    # 验证单项占比
    tool_audit = next(c for c in bill.components if c.component_kind == ContextComponentKind.TOOL_SCHEMAS)
    assert tool_audit.estimated_tokens == 300
    assert abs(tool_audit.ratio_of_budget - (300 / 900)) < 1e-4
    assert not tool_audit.is_bloated


def test_audit_opening_budget_bloat_detection_and_savings() -> None:
    """测试常驻冗长 Persona 膨胀告警与潜在节约 Token 预估。"""
    config = ContextDietConfig(
        total_window_capacity=128_000,
        persona_bloat_char_threshold=500,
        token_char_ratio=3.5,
    )
    engine = ContextDietEngine(config)

    # 超大个人履历背景 (2100 字符 -> 600 tokens)
    huge_persona = "My complete resume and coding rules background " * 45
    components = {
        ContextComponentKind.SYSTEM_PROMPT: "Base instructions",
        ContextComponentKind.STATIC_PERSONA: huge_persona,
    }

    bill = engine.audit_opening_budget(components)

    persona_audit = next(c for c in bill.components if c.component_kind == ContextComponentKind.STATIC_PERSONA)
    assert persona_audit.is_bloated is True
    assert "/about-me" in persona_audit.recommendation
    assert bill.potential_savings_tokens > 0


def test_distill_persona_to_invocable_skill() -> None:
    """测试将长篇背景一键蒸馏为轻量骨架指针与独立按需技能卡片。"""
    engine = ContextDietEngine()
    persona_bio = (
        "10年全栈工程师，擅长 Python、Rust 与分布式系统设计。"
        "偏好函数式编程范式，严禁在生产代码中使用隐式类型转换。"
        "曾经主导过高并发支付系统的架构重构与性能压测。" * 10
    )

    card: DistilledSkillCard = engine.distill_persona_to_invocable_skill(
        persona_text=persona_bio,
        skill_name="user_profile",
        trigger_command="/profile",
    )

    assert card.skill_name == "user_profile"
    assert card.trigger_command == "/profile"
    assert "user_profile" in card.skeleton_pointer
    assert "/profile" in card.skeleton_pointer
    assert card.full_content == persona_bio
    assert card.token_savings > 0
    assert card.created_at_iso is not None


def test_apply_unconstrained_creativity_diet() -> None:
    """测试纯净思维沙箱模式：剥离偏好底噪，释放原生无束缚推理极限。"""
    engine = ContextDietEngine()
    components = {
        ContextComponentKind.SYSTEM_PROMPT: "Think step by step.",
        ContextComponentKind.STATIC_PERSONA: "User prefers terse bullet points only and hates OOP.",
        ContextComponentKind.ENVIRONMENT_FACTS: "OS: Linux, Python 3.12",
    }

    # 1. 默认模式：彻底剥离人设与偏好
    purified_clean = engine.apply_unconstrained_creativity_diet(components, preserve_skeleton_pointer=False)
    assert purified_clean[ContextComponentKind.STATIC_PERSONA] == ""
    assert purified_clean[ContextComponentKind.SYSTEM_PROMPT] == "Think step by step."

    # 2. 保持骨架指引模式
    purified_skeleton = engine.apply_unconstrained_creativity_diet(components, preserve_skeleton_pointer=True)
    assert "第一性原理" in purified_skeleton[ContextComponentKind.STATIC_PERSONA]


def test_context_diet_engine_config_override() -> None:
    """测试在单次审计调用中动态覆盖配置。"""
    engine = ContextDietEngine(ContextDietConfig(total_window_capacity=50_000))

    components = {ContextComponentKind.SYSTEM_PROMPT: "Test system prompt"}

    override_config = ContextDietConfig(total_window_capacity=200_000)
    bill = engine.audit_opening_budget(components, config_override=override_config)

    assert bill.total_window_capacity == 200_000
