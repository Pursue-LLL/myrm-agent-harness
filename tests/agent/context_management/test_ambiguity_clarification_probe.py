"""Unit tests for Ambiguity Clarification Probe and Private Entity Graph Backtracking Suite.

Validates multi-level prompt ambiguity detection, missing constraint inquiry formulation,
private knowledge graph reverse-backtracking, and confirmable outline synthesis.
"""

from __future__ import annotations

from myrm_agent_harness.agent.context_management.ambiguity_probe import (
    AmbiguityClarificationProbe,
    AmbiguityLevel,
)


def test_highly_ambiguous_terse_prompt_detection() -> None:
    """Verifies that terse prompts with ungrounded honorifics/entities trigger high ambiguity with clarification questions."""
    probe = AmbiguityClarificationProbe()
    terse_prompt = "做一个给王总看的 PPT"

    result = probe.inspect_prompt(terse_prompt)
    assert result.level == AmbiguityLevel.HIGHLY_AMBIGUOUS
    assert result.is_ambiguous is True
    assert "王总" in result.detected_entities
    assert result.needs_backtracking is True
    assert len(result.clarification_questions) == 3

    # Check key dimensions in clarification inquiries
    dimensions = {q.dimension for q in result.clarification_questions}
    assert "target_audience" in dimensions
    assert "core_proposition" in dimensions
    assert "format_specification" in dimensions


def test_moderate_ambiguity_prompt_detection() -> None:
    """Verifies moderate ambiguity classification for longer prompts referencing ungrounded entities."""
    probe = AmbiguityClarificationProbe()
    moderate_prompt = "李经理希望我们在周五前把这次跨部门协作的复盘方案初步梳理出来"

    result = probe.inspect_prompt(moderate_prompt)
    assert result.level == AmbiguityLevel.MODERATE_AMBIGUOUS
    assert result.is_ambiguous is True
    assert "李经理" in result.detected_entities
    assert result.needs_backtracking is True
    assert len(result.clarification_questions) >= 1


def test_clear_prompt_bypasses_clarification() -> None:
    """Verifies that detailed prompts with explicit specs pass directly without ambiguity alarm."""
    probe = AmbiguityClarificationProbe()
    clear_prompt = (
        "请根据 docs/architecture/v2_spec.md 文档中第 4.2 节的规范，"
        "为数据管道编写包含 5 个核心过滤器的 Python 单元测试套件，并确保测试覆盖率达到 90% 以上。"
    )

    result = probe.inspect_prompt(clear_prompt)
    assert result.level == AmbiguityLevel.CLEAR
    assert result.is_ambiguous is False
    assert result.needs_backtracking is False
    assert len(result.clarification_questions) == 0


def test_private_entity_graph_backtracking_and_outline_synthesis() -> None:
    """Verifies reverse entity graph backtracking extracts facts from private corpus and synthesizes outline."""
    probe = AmbiguityClarificationProbe()

    # Simulated private corporate corpus (e.g. Feishu chat logs & meeting minutes)
    corpus = (
        {
            "title": "2026-08-17 盛联家电高层商务沟通纪要.md",
            "content": (
                "参会人：王总（盛联家电总经理王建国）、张总监。\n"
                "纪要要点：王总强调新产品必须符合六条静音与便携标准，重点对清风 Pro 便携小风扇表示浓厚兴趣。\n"
                "王总要求交付材料必须突出能效比与供应链交付周期。"
            ),
        },
        {
            "title": "群聊记录_盛联智能家居联合项目组.json",
            "content": "王总在群里回复：下周汇报请直接展示实测风噪分贝数据，少讲抽象概念。",
        },
    )

    dossier = probe.backtrack_entity_graph("王总", corpus)
    assert dossier.target_entity == "王总"
    assert len(dossier.matches) == 2
    assert dossier.matches[0].confidence_score >= 0.70
    assert len(dossier.synthesized_facts) >= 2

    # Verify synthesized outline draft incorporates backtracked facts
    outline = dossier.suggested_outline
    assert "[CONFIRMABLE PROPOSED OUTLINE: PREPARED FOR 王总]" in outline
    assert "清风 Pro 便携小风扇" in outline or "六条静音与便携标准" in outline
    assert "待用户一键确认生效" in outline
