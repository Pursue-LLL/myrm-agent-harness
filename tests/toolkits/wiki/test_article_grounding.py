"""The article stage writes from the text of the concept's sources, not from their file names.

The model has to quote numbers exactly and cite line ranges (the article template says so), which it cannot do
for a document it was only told the path of.
"""

from pathlib import Path
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage

from myrm_agent_harness.toolkits.wiki.core.config import WikiCompileConfig
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.core.types import ConceptInfo
from myrm_agent_harness.toolkits.wiki.pipeline.articles import generate_article
from myrm_agent_harness.toolkits.wiki.retrieval.indexer import WikiIndexer

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

_FILLER = "第 {i} 项例行事项：核对设备台账、更新排班表并归档上月的巡检记录，与定价无关。"
_FACTS = (
    "企业版年费为每席位 38,800 元，年付享 8.3 折。",
    "超过 200 席位的客户额外赠送 5% 席位。",
    "退款窗口为 17 天。",
)
_SOURCE_MARKER = "### "


class _CapturingLlm:
    """Records the prompts it is given; ``n_ctx`` is the context window attribute the budget reads."""

    def __init__(self, n_ctx: int | None = None) -> None:
        self.prompts: list[str] = []
        if n_ctx is not None:
            self.n_ctx = n_ctx

    async def ainvoke(self, messages: list[object]) -> AIMessage:
        self.prompts.append(str(getattr(messages[-1], "content", "")))
        return AIMessage(content="## Compiled Truth\nstub article")


@pytest.fixture
def structure(tmp_path: Path) -> WikiStructure:
    wiki = WikiStructure(tmp_path)
    wiki.ensure_structure()
    return wiki


def _long_manual(heading: str) -> str:
    lines = ["# 2026 年度运营手册", ""]
    lines += [_FILLER.format(i=i) for i in range(1, 330)]
    lines += ["", f"## {heading}", *_FACTS, f"以上就是{heading}的全部条款。"]
    lines += [_FILLER.format(i=i) for i in range(330, 700)]
    return "\n".join(lines) + "\n"


async def _write_article(
    structure: WikiStructure, llm: _CapturingLlm, concept: ConceptInfo, *, require_approval: bool = False
) -> str:
    indexer = AsyncMock(spec=WikiIndexer)
    indexer.upsert = AsyncMock()
    indexer.extract_and_upsert_edges = MagicMock()
    await generate_article(
        cast("BaseChatModel", llm),
        structure,
        WikiCompileConfig(require_approval=require_approval),
        indexer,
        concept,
    )
    return llm.prompts[-1]


def _concept(name: str, *sources: str, definition: str = "d") -> ConceptInfo:
    return ConceptInfo(name=name, definition=definition, mentions=2, source_files=list(sources))


def _line_number(document: str, fragment: str) -> int:
    return next(n for n, line in enumerate(document.splitlines(), 1) if fragment in line)


def _source_part(prompt: str) -> str:
    """What the template's source slot holds: from the first source header up to the formatting rules."""
    return prompt.split(_SOURCE_MARKER, 1)[1].split("\n\nCRITICAL", 1)[0]


def test_the_template_has_no_concrete_citation_example_for_the_model_to_copy() -> None:
    # A model that is shown "L42-45" writes it into articles whose sources have no such lines.
    template = WikiCompileConfig().generate_article_prompt_template

    assert "L42-45" not in template
    assert "L<first>-<last>" in template
    assert '"<first>-<last>"' in template


@pytest.mark.asyncio
async def test_the_prompt_carries_the_text_of_the_source_with_its_real_line_numbers(structure: WikiStructure) -> None:
    (structure.raw_dir / "pricing.md").write_text("# Pricing\n\nThe annual fee is 38,800 CNY.\n", encoding="utf-8")

    prompt = await _write_article(structure, _CapturingLlm(), _concept("Pricing", "raw/pricing.md"))

    assert "### raw/pricing.md" in prompt
    assert "1| # Pricing" in prompt
    assert "3| The annual fee is 38,800 CNY." in prompt


@pytest.mark.asyncio
async def test_every_source_of_a_concept_reaches_the_prompt_in_a_fixed_order(structure: WikiStructure) -> None:
    (structure.raw_dir / "a.md").write_text("alpha fact\n", encoding="utf-8")
    (structure.raw_dir / "b.md").write_text("beta fact\n", encoding="utf-8")

    forward = await _write_article(structure, _CapturingLlm(), _concept("Both", "raw/a.md", "raw/b.md"))
    backward = await _write_article(structure, _CapturingLlm(), _concept("Both", "raw/b.md", "raw/a.md"))

    assert "1| alpha fact" in forward
    assert "1| beta fact" in forward
    assert forward.index("raw/a.md") < forward.index("raw/b.md")
    # A retry (or a restarted worker that merged the sources in another order) sends the same bytes.
    assert _source_part(forward) == _source_part(backward)


@pytest.mark.asyncio
async def test_a_document_longer_than_the_budget_keeps_the_lines_about_the_concept(structure: WikiStructure) -> None:
    document = _long_manual("企业版定价政策")
    (structure.raw_dir / "ops.md").write_text(document, encoding="utf-8")
    concept = _concept("企业版定价政策", "raw/ops.md", definition="企业版年费与折扣规则")

    prompt = await _write_article(structure, _CapturingLlm(), concept)

    for fact in _FACTS:
        assert f"{_line_number(document, fact)}| {fact}" in prompt
    assert len(prompt) < len(document) // 2


@pytest.mark.asyncio
async def test_lines_about_the_concept_are_found_when_the_document_names_it_differently(
    structure: WikiStructure,
) -> None:
    document = _long_manual("旗舰套餐价目规则")
    (structure.raw_dir / "ops.md").write_text(document, encoding="utf-8")
    concept = _concept("企业版定价政策", "raw/ops.md", definition="企业版年费与折扣规则")

    prompt = await _write_article(structure, _CapturingLlm(), concept)

    for fact in _FACTS:
        assert f"{_line_number(document, fact)}| {fact}" in prompt


@pytest.mark.asyncio
async def test_a_model_with_a_small_window_gets_a_proportionally_small_source_excerpt(structure: WikiStructure) -> None:
    document = _long_manual("企业版定价政策")
    (structure.raw_dir / "ops.md").write_text(document, encoding="utf-8")
    concept = _concept("企业版定价政策", "raw/ops.md", definition="企业版年费与折扣规则")

    roomy = await _write_article(structure, _CapturingLlm(), concept)
    cramped = await _write_article(structure, _CapturingLlm(n_ctx=4_000), concept)

    # A quarter of the window, a character counted as a token: 1,000 characters of source for 4,000 tokens.
    assert len(_source_part(cramped)) <= 1_100
    assert len(cramped) < len(roomy)


@pytest.mark.asyncio
async def test_a_source_that_is_gone_or_unreadable_is_listed_by_path_and_does_not_fail_the_article(
    structure: WikiStructure,
) -> None:
    (structure.raw_dir / "binary.md").write_bytes(b"\xff\xfe\x00\x81 not utf-8")
    concept = _concept("Gone", "raw/missing.md", "raw/binary.md")

    prompt = await _write_article(structure, _CapturingLlm(), concept)

    assert "### raw/missing.md" in prompt
    assert "### raw/binary.md" in prompt
    assert "not utf-8" not in prompt


@pytest.mark.asyncio
async def test_braces_in_a_source_do_not_break_the_template(structure: WikiStructure) -> None:
    (structure.raw_dir / "code.md").write_text("config = {concept_name}; fmt = {0} {source_docs}\n", encoding="utf-8")

    prompt = await _write_article(structure, _CapturingLlm(), _concept("Braces", "raw/code.md"))

    assert "1| config = {concept_name}; fmt = {0} {source_docs}" in prompt
    assert prompt.startswith("Generate a comprehensive wiki article for the concept: Braces")


@pytest.mark.asyncio
async def test_an_existing_article_still_follows_the_sources(structure: WikiStructure) -> None:
    (structure.raw_dir / "a.md").write_text("fresh fact\n", encoding="utf-8")
    structure.get_concept_file_path("Known").write_text("## Compiled Truth\nold\n## Timeline\n- t0\n", encoding="utf-8")

    prompt = await _write_article(structure, _CapturingLlm(), _concept("Known", "raw/a.md"))

    assert prompt.index("1| fresh fact") < prompt.index("# Existing Wiki Content")
    assert prompt.rstrip().endswith("- t0")
