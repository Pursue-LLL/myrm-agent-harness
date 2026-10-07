"""单元测试：个人画像与专业偏好全域按需水合与大模型创造力保鲜套件。

[INPUT]
- OnDemandContextHydrator 及相关领域契约

[OUTPUT]
- 验证显式快捷指令水合、隐式语义意图动态水合、创造力保鲜严格旁路、通用问答零污染。

[POS]
- 位于 tests/agent/context_management/test_on_demand_context_hydrator.py
"""

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
import pytest

from myrm_agent_harness.agent.context_management.demand_hydration import (
    DemandHydrationConfig,
    HydrationTriggerMode,
    OnDemandContextHydrator,
    ProfileCardCategory,
    UserMemoryCard,
)


def _build_test_cards() -> list[UserMemoryCard]:
    return [
        UserMemoryCard(
            card_id="coding_python_style",
            title="Python Coding Style",
            category=ProfileCardCategory.CODING_STYLE,
            content="Strict PEP8, never use Any, always prefer concise dataclasses and pure functions.",
            token_estimate=25,
            tags=["python", "coding", "style"],
        ),
        UserMemoryCard(
            card_id="writing_tone_concise",
            title="Executive Writing Tone",
            category=ProfileCardCategory.WRITING_TONE,
            content="Clear, objective, bulleted summaries, no generic flattery or marketing filler.",
            token_estimate=20,
            tags=["email", "writing", "tone"],
        ),
        UserMemoryCard(
            card_id="architecture_standard",
            title="Microservice Standard",
            category=ProfileCardCategory.ARCHITECTURE_STANDARD,
            content="Single responsibility per module, file under 400 lines, explicit interfaces.",
            token_estimate=30,
            tags=["architecture", "standard"],
        ),
    ]


def test_explicit_command_hydration() -> None:
    """验证用户通过快捷命令 (/about-me 或 /card:xxx) 显式即时水合卡片。"""
    hydrator = OnDemandContextHydrator()
    hydrator.register_cards(_build_test_cards())

    messages = [
        SystemMessage(content="You are an expert AI assistant."),
        HumanMessage(content="Hello, configure my preferences."),
    ]

    # 1. /about-me 命令水合
    envelope = hydrator.hydrate_context(messages=messages, explicit_command="/about-me")
    assert envelope.decision.should_hydrate is True
    assert envelope.decision.trigger_mode == HydrationTriggerMode.EXPLICIT_COMMAND
    assert len(envelope.decision.hydrated_cards) > 0
    assert envelope.injected_tokens > 0

    # 验证水合系统卡片被正确注入到上下文
    injected_texts = [str(m.content) for m in envelope.hydrated_messages if isinstance(m, SystemMessage)]
    assert any("[On-Demand Context Hydration]" in txt for txt in injected_texts)
    assert any("Python Coding Style" in txt for txt in injected_texts)


def test_creativity_preservation_strict_bypass() -> None:
    """验证开放式创意探讨/头脑风暴时严格旁路画像注入，大模型原生创造力 100% 保鲜。"""
    hydrator = OnDemandContextHydrator()
    hydrator.register_cards(_build_test_cards())

    creative_messages = [
        SystemMessage(content="Base system."),
        HumanMessage(content="Let's do a wild brainstorm for new product ideas, bring creative divergence!"),
    ]

    envelope = hydrator.hydrate_context(messages=creative_messages)
    assert envelope.decision.should_hydrate is False
    assert envelope.decision.trigger_mode == HydrationTriggerMode.CREATIVITY_BYPASS
    assert envelope.decision.creativity_preserved is True
    assert len(envelope.decision.hydrated_cards) == 0
    assert envelope.injected_tokens == 0
    # 消息列表完全原样保留，零污染
    assert envelope.hydrated_messages == creative_messages


def test_implicit_semantic_routing_coding() -> None:
    """验证语义分类器识别代码开发意图，自动动态水合编码风格卡片。"""
    hydrator = OnDemandContextHydrator()
    hydrator.register_cards(_build_test_cards())

    coding_messages = [
        SystemMessage(content="Base system."),
        HumanMessage(content="Please refactor this Python class to eliminate bug and optimize speed."),
    ]

    envelope = hydrator.hydrate_context(messages=coding_messages)
    assert envelope.decision.should_hydrate is True
    assert envelope.decision.trigger_mode == HydrationTriggerMode.IMPLICIT_ROUTING
    assert any(c.category == ProfileCardCategory.CODING_STYLE for c in envelope.decision.hydrated_cards)
    assert envelope.injected_tokens > 0


def test_zero_pollution_clean_baseline() -> None:
    """验证日常通用问答不触发任何水合，零 Token 浪费，常驻 Prompt 极致精炼。"""
    hydrator = OnDemandContextHydrator()
    hydrator.register_cards(_build_test_cards())

    generic_messages = [
        SystemMessage(content="Base system."),
        HumanMessage(content="What is the distance between Earth and Mars?"),
    ]

    envelope = hydrator.hydrate_context(messages=generic_messages)
    assert envelope.decision.should_hydrate is False
    assert len(envelope.decision.hydrated_cards) == 0
    assert envelope.injected_tokens == 0
    assert envelope.hydrated_messages == generic_messages
