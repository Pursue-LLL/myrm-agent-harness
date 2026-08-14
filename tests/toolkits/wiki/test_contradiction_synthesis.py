"""Tests for compile-time contradiction synthesis (CCSP)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.core.types import ConceptInfo
from myrm_agent_harness.toolkits.wiki.pipeline.contradiction_synthesis.backlink import (
    apply_synthesis_backlinks,
)
from myrm_agent_harness.toolkits.wiki.pipeline.contradiction_synthesis.pairing import (
    collect_concept_pairs,
)
from myrm_agent_harness.toolkits.wiki.pipeline.contradiction_synthesis.service import (
    run_contradiction_synthesis_pass,
)
from myrm_agent_harness.toolkits.wiki.pipeline.contradiction_synthesis.types import (
    ConceptPair,
    ConflictVerdict,
)
from myrm_agent_harness.toolkits.wiki.pipeline.contradiction_synthesis.writer import (
    build_evolution_concept_path,
    build_synthesis_page,
    parse_synthesis_backlink_targets,
)


@pytest.fixture
def temp_wiki(tmp_path) -> WikiStructure:
    structure = WikiStructure(tmp_path / "wiki-ccsp")
    structure.ensure_structure()
    return structure


def test_collect_concept_pairs_related_concept(temp_wiki: WikiStructure) -> None:
    batch = [
        ConceptInfo(
            name="AI/Agent-A",
            definition="Agent is autonomous",
            related_concepts=["AI/Agent-B"],
        ),
        ConceptInfo(name="AI/Agent-B", definition="Agent is a tool", related_concepts=[]),
    ]
    pairs = collect_concept_pairs(batch, temp_wiki)
    assert len(pairs) == 1
    assert pairs[0].reason == "related_concept"


def test_collect_concept_pairs_shared_slug(temp_wiki: WikiStructure) -> None:
    batch = [
        ConceptInfo(name="Notes/Agent", definition="Definition A"),
        ConceptInfo(name="Research/Agent", definition="Definition B"),
    ]
    pairs = collect_concept_pairs(batch, temp_wiki)
    assert len(pairs) == 1
    assert pairs[0].reason == "shared_slug"


def test_build_evolution_concept_path() -> None:
    assert build_evolution_concept_path("Agent 定义").startswith("Comparisons/")


def test_build_synthesis_page_contains_wikilinks(temp_wiki: WikiStructure) -> None:
    verdict = ConflictVerdict(
        is_factual_conflict=True,
        confidence=0.9,
        topic="Agent",
        side_a="Agent is autonomous",
        side_b="Agent is a passive tool",
        resolution_hint="Decide which definition matches your workflow.",
    )
    pair = ConceptPair(concept_a="AI/Agent-A", concept_b="AI/Agent-B", reason="related_concept")
    concept_path, content = build_synthesis_page(verdict, pair)
    assert concept_path.startswith("Comparisons/")
    assert "[[AI/Agent-A]]" in content
    assert "[[AI/Agent-B]]" in content
    assert "synthesis_kind: evolution" in content
    linked = parse_synthesis_backlink_targets(content)
    assert linked == ("AI/Agent-A", "AI/Agent-B")


@pytest.mark.asyncio
async def test_run_contradiction_synthesis_pass_stages_pending(
    temp_wiki: WikiStructure,
) -> None:
    batch = [
        ConceptInfo(
            name="AI/Agent-A",
            definition="Agent is autonomous",
            related_concepts=["AI/Agent-B"],
        ),
        ConceptInfo(name="AI/Agent-B", definition="Agent is a tool", related_concepts=[]),
    ]
    llm = MagicMock()
    llm.ainvoke = AsyncMock(
        return_value=MagicMock(
            content=(
                '{"is_factual_conflict": true, "confidence": 0.91, "topic": "Agent", '
                '"side_a": "autonomous", "side_b": "tool", "resolution_hint": "Pick one."}'
            )
        )
    )
    from myrm_agent_harness.toolkits.wiki.core.config import WikiCompileConfig
    from myrm_agent_harness.toolkits.wiki.pipeline.pending import (
        WikiPendingEditsManager,
    )

    result = await run_contradiction_synthesis_pass(
        llm,
        temp_wiki,
        WikiCompileConfig(),
        None,
        batch,
    )
    assert result.pairs_considered == 1
    assert result.synthesis_staged == 1
    pending = WikiPendingEditsManager(temp_wiki, None).get_pending_edits()
    assert len(pending) == 1
    assert pending[0]["concept_name"].startswith("Comparisons/")


@pytest.mark.asyncio
async def test_run_contradiction_synthesis_reasoning_model_content_empty(
    temp_wiki: WikiStructure,
) -> None:
    """Reasoning 模型 content 为空时回退到 additional_kwargs["reasoning_content"]。"""
    batch = [
        ConceptInfo(
            name="AI/Agent-A",
            definition="Agent is autonomous",
            related_concepts=["AI/Agent-B"],
        ),
        ConceptInfo(name="AI/Agent-B", definition="Agent is a tool", related_concepts=[]),
    ]
    llm = MagicMock()
    llm.ainvoke = AsyncMock(
        return_value=MagicMock(
            content="",
            additional_kwargs={
                "reasoning_content": (
                    '{"is_factual_conflict": true, "confidence": 0.91, "topic": "Agent", '
                    '"side_a": "autonomous", "side_b": "tool", "resolution_hint": "Pick one."}'
                )
            },
        )
    )
    from myrm_agent_harness.toolkits.wiki.core.config import WikiCompileConfig

    result = await run_contradiction_synthesis_pass(
        llm,
        temp_wiki,
        WikiCompileConfig(),
        None,
        batch,
    )
    assert result.pairs_considered == 1
    assert result.synthesis_staged == 1


def test_build_synthesis_page_uses_cjk_body_for_cjk_topic() -> None:
    verdict = ConflictVerdict(
        is_factual_conflict=True,
        confidence=0.88,
        topic="Agent 定义",
        side_a="Agent 是自主体",
        side_b="Agent 是被动工具",
        resolution_hint="请决定哪条定义优先。",
    )
    pair = ConceptPair(concept_a="AI/Agent-A", concept_b="AI/Agent-B", reason="related_concept")
    _, content = build_synthesis_page(verdict, pair)
    assert "Agent 定义的演变" in content
    assert "本页记录" in content
    assert "建议下一步" in content
    assert "编译批次合成待审" in content
    assert "This page tracks a factual conflict" not in content


@pytest.mark.asyncio
async def test_detect_conflict_high_confidence_verdict(
    temp_wiki: WikiStructure,
) -> None:
    """detect_conflict returns a verdict when LLM reports a high-confidence conflict."""
    from langchain_core.messages import AIMessage

    from myrm_agent_harness.toolkits.wiki.pipeline.contradiction_synthesis.detector import (
        detect_conflict,
    )

    llm = MagicMock()
    llm.ainvoke = AsyncMock(
        return_value=AIMessage(
            content=(
                '{"is_factual_conflict": true, "confidence": 0.92, "topic": "Agent", '
                '"side_a": "autonomous", "side_b": "tool", "resolution_hint": "Pick one."}'
            )
        )
    )
    pair = ConceptPair(concept_a="AI/Agent-A", concept_b="AI/Agent-B", reason="related_concept")
    verdict = await detect_conflict(
        llm,
        temp_wiki,
        pair,
        definition_a="Agent is autonomous",
        definition_b="Agent is a tool",
    )
    assert verdict is not None
    assert verdict.is_factual_conflict is True
    assert verdict.confidence == 0.92
    assert verdict.topic == "Agent"


@pytest.mark.asyncio
async def test_detect_conflict_reasoning_model_content_empty(
    temp_wiki: WikiStructure,
) -> None:
    """detect_conflict falls back to reasoning_content when content is empty."""
    from myrm_agent_harness.toolkits.wiki.pipeline.contradiction_synthesis.detector import (
        detect_conflict,
    )

    llm = MagicMock()
    llm.ainvoke = AsyncMock(
        return_value=MagicMock(
            content="",
            additional_kwargs={
                "reasoning_content": (
                    '{"is_factual_conflict": true, "confidence": 0.85, "topic": "Agent", '
                    '"side_a": "autonomous", "side_b": "tool", "resolution_hint": "Review."}'
                )
            },
        )
    )
    pair = ConceptPair(concept_a="AI/Agent-A", concept_b="AI/Agent-B", reason="related_concept")
    verdict = await detect_conflict(
        llm,
        temp_wiki,
        pair,
        definition_a="Agent is autonomous",
        definition_b="Agent is a tool",
    )
    assert verdict is not None
    assert verdict.confidence == 0.85


@pytest.mark.asyncio
async def test_detect_conflict_low_confidence_returns_none(
    temp_wiki: WikiStructure,
) -> None:
    """detect_conflict returns None when confidence is below the threshold."""
    from langchain_core.messages import AIMessage

    from myrm_agent_harness.toolkits.wiki.pipeline.contradiction_synthesis.detector import (
        detect_conflict,
    )

    llm = MagicMock()
    llm.ainvoke = AsyncMock(
        return_value=AIMessage(
            content=(
                '{"is_factual_conflict": false, "confidence": 0.4, "topic": "Agent", '
                '"side_a": "autonomous", "side_b": "tool", "resolution_hint": ""}'
            )
        )
    )
    pair = ConceptPair(concept_a="AI/Agent-A", concept_b="AI/Agent-B", reason="related_concept")
    verdict = await detect_conflict(
        llm,
        temp_wiki,
        pair,
        definition_a="Agent is autonomous",
        definition_b="Agent is a tool",
    )
    assert verdict is None


@pytest.mark.asyncio
async def test_detect_conflict_invalid_json_returns_none(
    temp_wiki: WikiStructure,
) -> None:
    """detect_conflict returns None on malformed LLM output without raising."""
    from langchain_core.messages import AIMessage

    from myrm_agent_harness.toolkits.wiki.pipeline.contradiction_synthesis.detector import (
        detect_conflict,
    )

    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=AIMessage(content="I could not determine a conflict."))
    pair = ConceptPair(concept_a="AI/Agent-A", concept_b="AI/Agent-B", reason="related_concept")
    verdict = await detect_conflict(
        llm,
        temp_wiki,
        pair,
        definition_a="Agent is autonomous",
        definition_b="Agent is a tool",
    )
    assert verdict is None


@pytest.mark.asyncio
async def test_detect_conflict_robust_json_parsing(
    temp_wiki: WikiStructure,
) -> None:
    """detect_conflict tolerates prose framing and trailing commas in LLM verdict."""
    from langchain_core.messages import AIMessage

    from myrm_agent_harness.toolkits.wiki.pipeline.contradiction_synthesis.detector import (
        detect_conflict,
    )

    llm = MagicMock()
    llm.ainvoke = AsyncMock(
        return_value=AIMessage(
            content=(
                "Assessment of the pair:\n"
                '{"is_factual_conflict": true, "confidence": 0.9, '
                '"topic": "Agent", "side_a": "autonomous", "side_b": "tool", '
                '"resolution_hint": "Unify definitions",}'
            )
        )
    )
    pair = ConceptPair(concept_a="AI/Agent-A", concept_b="AI/Agent-B", reason="related_concept")
    verdict = await detect_conflict(
        llm,
        temp_wiki,
        pair,
        definition_a="Agent is autonomous",
        definition_b="Agent is a tool",
    )
    assert verdict is not None
    assert verdict.is_factual_conflict is True
    assert verdict.confidence == 0.9


@pytest.mark.asyncio
async def test_detect_conflict_reads_existing_concept_file(
    temp_wiki: WikiStructure,
) -> None:
    """detect_conflict uses the compiled truth summary from existing concept files."""
    from langchain_core.messages import AIMessage

    from myrm_agent_harness.toolkits.wiki.core.section_contract import (
        build_note_body_skeleton,
    )
    from myrm_agent_harness.toolkits.wiki.pipeline.contradiction_synthesis.detector import (
        detect_conflict,
    )

    path_a = temp_wiki.get_concept_file_path("AI/Agent-A")
    path_a.write_text(build_note_body_skeleton(compiled_truth="Agent is autonomous", timeline_entry=""))
    path_b = temp_wiki.get_concept_file_path("AI/Agent-B")
    path_b.write_text(build_note_body_skeleton(compiled_truth="Agent is a tool", timeline_entry=""))

    llm = MagicMock()
    llm.ainvoke = AsyncMock(
        return_value=AIMessage(
            content=(
                '{"is_factual_conflict": true, "confidence": 0.9, "topic": "Agent", '
                '"side_a": "autonomous", "side_b": "tool", "resolution_hint": "Pick one."}'
            )
        )
    )
    pair = ConceptPair(concept_a="AI/Agent-A", concept_b="AI/Agent-B", reason="related_concept")
    verdict = await detect_conflict(llm, temp_wiki, pair, definition_a="", definition_b="")
    assert verdict is not None
    assert verdict.side_a == "autonomous"


@pytest.mark.asyncio
async def test_detect_conflict_exception_safe(temp_wiki: WikiStructure) -> None:
    """detect_conflict returns None when the LLM call raises."""
    from myrm_agent_harness.toolkits.wiki.pipeline.contradiction_synthesis.detector import (
        detect_conflict,
    )

    llm = MagicMock()
    llm.ainvoke = AsyncMock(side_effect=RuntimeError("provider down"))
    pair = ConceptPair(concept_a="AI/Agent-A", concept_b="AI/Agent-B", reason="related_concept")
    verdict = await detect_conflict(
        llm,
        temp_wiki,
        pair,
        definition_a="Agent is autonomous",
        definition_b="Agent is a tool",
    )
    assert verdict is None


@pytest.mark.asyncio
async def test_apply_synthesis_backlinks_appends_timeline_on_linked_concept(
    temp_wiki: WikiStructure,
) -> None:
    from myrm_agent_harness.toolkits.wiki.core.frontmatter_contract import (
        WikiPageType,
        ensure_frontmatter_type,
    )
    from myrm_agent_harness.toolkits.wiki.core.section_contract import (
        build_note_body_skeleton,
    )
    from myrm_agent_harness.toolkits.wiki.pipeline.publication import (
        publish_concept_article,
    )

    concept_a = "AI/Agent-A"
    concept_b = "AI/Agent-B"
    for concept_name, truth in (
        (concept_a, "Agent is autonomous"),
        (concept_b, "Agent is a tool"),
    ):
        body = build_note_body_skeleton(compiled_truth=truth, timeline_entry="Initial note.")
        content = ensure_frontmatter_type(body, WikiPageType.CONCEPT)
        await publish_concept_article(temp_wiki, None, concept_name, content)

    verdict = ConflictVerdict(
        is_factual_conflict=True,
        confidence=0.9,
        topic="Agent",
        side_a="autonomous",
        side_b="tool",
        resolution_hint="Pick one.",
    )
    pair = ConceptPair(concept_a=concept_a, concept_b=concept_b, reason="related_concept")
    synthesis_path, synthesis_content = build_synthesis_page(verdict, pair)

    updated = await apply_synthesis_backlinks(
        temp_wiki,
        None,
        synthesis_concept_name=synthesis_path,
        synthesis_content=synthesis_content,
    )
    assert updated == 2
    linked_a = temp_wiki.get_concept_file_path(concept_a).read_text(encoding="utf-8")
    linked_b = temp_wiki.get_concept_file_path(concept_b).read_text(encoding="utf-8")
    assert f"[[{synthesis_path}]]" in linked_a
    assert f"[[{synthesis_path}]]" in linked_b


@pytest.mark.asyncio
async def test_apply_synthesis_backlinks_uses_cjk_timeline_entry(
    temp_wiki: WikiStructure,
) -> None:
    from myrm_agent_harness.toolkits.wiki.core.frontmatter_contract import (
        WikiPageType,
        ensure_frontmatter_type,
    )
    from myrm_agent_harness.toolkits.wiki.core.section_contract import (
        build_note_body_skeleton,
    )
    from myrm_agent_harness.toolkits.wiki.pipeline.publication import (
        publish_concept_article,
    )

    concept_a = "AI/产品-Agent"
    concept_b = "AI/研究-Agent"
    for concept_name, truth in (
        (concept_a, "Agent 是产品助手"),
        (concept_b, "Agent 是研究工具"),
    ):
        body = build_note_body_skeleton(compiled_truth=truth, timeline_entry="初始记录。")
        content = ensure_frontmatter_type(body, WikiPageType.CONCEPT)
        await publish_concept_article(temp_wiki, None, concept_name, content)

    verdict = ConflictVerdict(
        is_factual_conflict=True,
        confidence=0.9,
        topic="Agent 定义",
        side_a="产品助手",
        side_b="研究工具",
        resolution_hint="请决定哪条定义优先。",
    )
    pair = ConceptPair(concept_a=concept_a, concept_b=concept_b, reason="related_concept")
    synthesis_path, synthesis_content = build_synthesis_page(verdict, pair)

    updated = await apply_synthesis_backlinks(
        temp_wiki,
        None,
        synthesis_concept_name=synthesis_path,
        synthesis_content=synthesis_content,
    )
    assert updated == 2
    linked_a = temp_wiki.get_concept_file_path(concept_a).read_text(encoding="utf-8")
    assert "冲突合成已发布" in linked_a
    assert "Conflict synthesis published" not in linked_a
