from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage

from myrm_agent_harness.toolkits.wiki.core.config import WikiCompileConfig
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.core.types import ConceptInfo
from myrm_agent_harness.toolkits.wiki.pipeline.sidecar import build_directory_sidecars


class _FakeIndexer:
    def __init__(self) -> None:
        self.upserts: list[tuple[str, int, str]] = []
        self.deletes: list[tuple[str, int]] = []
        self.delete_all_calls = 0

    async def upsert_sidecar(self, dir_path: str, *, level: int, content: str) -> None:
        self.upserts.append((dir_path, level, content))

    async def delete_sidecar(self, dir_path: str, *, level: int) -> None:
        self.deletes.append((dir_path, level))

    async def delete_all_sidecars(self) -> None:
        self.delete_all_calls += 1


@pytest.mark.asyncio
async def test_sidecar_builder_incremental_skip(tmp_path):
    structure = WikiStructure(tmp_path)
    structure.ensure_structure()
    concept_file = structure.get_concept_file_path("Ops/Runbook")
    concept_file.write_text("## Compiled Truth\nRunbook steps and rollback plan.", encoding="utf-8")

    llm = AsyncMock()
    llm.ainvoke.return_value = AIMessage(
        content='{"abstract":"Ops summary","overview":"Ops detailed overview"}'
    )
    indexer = _FakeIndexer()
    concept = ConceptInfo(
        name="Ops/Runbook",
        definition="Runbook",
        source_files=["ops.md"],
        related_concepts=[],
    )

    first = await build_directory_sidecars(
        llm,
        structure,
        WikiCompileConfig(),
        touched_concepts=[concept],
        indexer=indexer,
    )
    assert first.rebuilt_directories >= 1
    assert llm.ainvoke.await_count >= 1

    abstract_path, overview_path = structure.get_directory_sidecar_paths("ops", create=False)
    assert abstract_path.exists()
    assert overview_path.exists()
    assert "summary" in abstract_path.read_text(encoding="utf-8").lower()

    before_count = llm.ainvoke.await_count
    second = await build_directory_sidecars(
        llm,
        structure,
        WikiCompileConfig(),
        touched_concepts=[],
        indexer=indexer,
    )
    assert second.skipped_directories >= 1
    assert llm.ainvoke.await_count == before_count


@pytest.mark.asyncio
async def test_sidecar_builder_clears_sidecars_when_no_concepts(tmp_path):
    structure = WikiStructure(tmp_path)
    structure.ensure_structure()
    concept_file = structure.get_concept_file_path("Domain/Topic")
    concept_file.write_text("## Compiled Truth\nKnowledge.", encoding="utf-8")

    llm = AsyncMock()
    llm.ainvoke.return_value = AIMessage(
        content='{"abstract":"Domain summary","overview":"Domain overview"}'
    )
    indexer = _FakeIndexer()
    concept = ConceptInfo(
        name="Domain/Topic",
        definition="Topic",
        source_files=["domain.md"],
        related_concepts=[],
    )
    await build_directory_sidecars(
        llm,
        structure,
        WikiCompileConfig(),
        touched_concepts=[concept],
        indexer=indexer,
    )
    concept_file.unlink()

    result = await build_directory_sidecars(
        llm,
        structure,
        WikiCompileConfig(),
        touched_concepts=[],
        indexer=indexer,
    )
    assert result.removed_directories >= 1
    assert indexer.delete_all_calls == 1


@pytest.mark.asyncio
async def test_sidecar_builder_reasoning_model_content_empty(tmp_path):
    """Reasoning 模型 content 为空时回退到 additional_kwargs["reasoning_content"]。"""
    structure = WikiStructure(tmp_path)
    structure.ensure_structure()
    concept_file = structure.get_concept_file_path("Ops/Runbook")
    concept_file.write_text("## Compiled Truth\nRunbook steps and rollback plan.", encoding="utf-8")

    llm = AsyncMock()
    llm.ainvoke.return_value = AIMessage(
        content="",
        additional_kwargs={"reasoning_content": '{"abstract":"Ops summary","overview":"Ops detailed overview"}'},
    )
    indexer = _FakeIndexer()
    concept = ConceptInfo(
        name="Ops/Runbook",
        definition="Runbook",
        source_files=["ops.md"],
        related_concepts=[],
    )

    result = await build_directory_sidecars(
        llm,
        structure,
        WikiCompileConfig(),
        touched_concepts=[concept],
        indexer=indexer,
    )
    assert result.rebuilt_directories >= 1
    abstract_path, overview_path = structure.get_directory_sidecar_paths("ops", create=False)
    assert "summary" in abstract_path.read_text(encoding="utf-8").lower()
