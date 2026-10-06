# [POS] tests/toolkits/memory/test_memory_persona_router.py
# [INPUT] types, gate, router
# [OUTPUT] test_technical_execution_intent_100_percent_suppression, test_creative_communication_intent_contextual_activation, test_explicit_about_me_directive_forces_activation, test_facet_switching_and_default_fallback

from myrm_agent_harness.toolkits.memory.persona_router import (
    AntiPollutionContextRouter,
    PersonaFacet,
    StyleSuppressionGate,
    TaskIntentCategory,
)


def _sample_facets() -> list[PersonaFacet]:
    """Helper providing standard test persona facets."""
    return [
        PersonaFacet(
            facet_id="executive",
            name="商业高管汇报态",
            tone_guidance="遵循金字塔原理，结论先行，强调商业价值与 ROI",
            sample_excerpts=("本季度核心业务增长 35%，主要受海外拓展拉动。",),
            target_intents=("creative_communication", "business"),
            is_default=True,
            estimated_tokens=200,
        ),
        PersonaFacet(
            facet_id="engineer",
            name="技术极客极简态",
            tone_guidance="极致凝练，直出关键代码与架构逻辑，严禁客套",
            sample_excerpts=("零拷贝流式转发已就绪，内存开销降低 40%。",),
            target_intents=("technical_execution", "tech"),
            is_default=False,
            estimated_tokens=150,
        ),
    ]


def test_technical_execution_intent_100_percent_suppression() -> None:
    """Verify code, CLI, and debugging queries 100% suppress persona tokens to prevent pollution."""
    router = AntiPollutionContextRouter()
    facets = _sample_facets()

    technical_queries = [
        "请帮我编写一个 Dockerfile 并排查容器端口映射报错",
        "```python\ndef sanitize(): pass\n``` 调试这个函数的异常",
        "运行 git status 并检查 pytest 测试覆盖率",
    ]

    for q in technical_queries:
        decision = router.route(query=q, facets=facets)
        assert decision.is_suppressed is True
        assert decision.intent_category == TaskIntentCategory.TECHNICAL_EXECUTION
        assert decision.injected_content == ""
        assert len(decision.active_facets) == 0
        assert decision.tokens_saved_estimate == 350
        assert "suppressed" in decision.decision_reason.lower()


def test_creative_communication_intent_contextual_activation() -> None:
    """Verify creative writing and business communications activate matching persona facet."""
    router = AntiPollutionContextRouter()
    facets = _sample_facets()

    creative_query = "请帮我撰写一份关于季度架构升级成果的公关稿与对外汇报邮件"
    decision = router.route(query=creative_query, facets=facets)

    assert decision.is_suppressed is False
    assert decision.intent_category == TaskIntentCategory.CREATIVE_COMMUNICATION
    assert "executive" in decision.active_facets
    assert "商业高管汇报态" in decision.injected_content
    assert "金字塔原理" in decision.injected_content
    assert decision.tokens_saved_estimate == 150  # saved engineer facet tokens


def test_explicit_about_me_directive_forces_activation() -> None:
    """Verify explicit /about-me directive forces activation even on technical code queries."""
    router = AntiPollutionContextRouter()
    facets = _sample_facets()

    # User asks for python code but explicitly requests /about-me:engineer style
    query = "请用 python 重写这个解析器，并遵循 /about-me:engineer 风格"
    decision = router.route(query=query, facets=facets)

    assert decision.is_suppressed is False
    assert "engineer" in decision.active_facets
    assert "技术极客极简态" in decision.injected_content
    assert "零拷贝" in decision.injected_content
    assert decision.tokens_saved_estimate == 200  # saved executive facet tokens


def test_facet_switching_and_default_fallback() -> None:
    """Verify explicit facet id argument and default fallback mechanism."""
    gate = StyleSuppressionGate()
    router = AntiPollutionContextRouter(gate=gate)
    facets = _sample_facets()

    # Explicitly target executive facet
    decision = router.route(
        query="帮我拟一份项目周报",
        facets=facets,
        explicit_facet_id="executive",
    )
    assert decision.is_suppressed is False
    assert decision.active_facets == ("executive",)

    # Empty facets list gracefully handled
    decision_empty = router.route(
        query="帮我拟一份项目周报",
        facets=[],
    )
    assert decision_empty.is_suppressed is True
    assert decision_empty.injected_content == ""
