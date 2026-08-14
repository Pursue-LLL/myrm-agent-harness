"""Integration tests for compile survey session seed carry-forward."""

from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from myrm_agent_harness.toolkits.wiki.core.config import WikiCompileConfig, WikiConfig
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.pipeline.compiler import WikiCompiler
from myrm_agent_harness.toolkits.wiki.pipeline.queue import WikiIngestionQueue
from myrm_agent_harness.toolkits.wiki.retrieval.indexer import WikiIndexer


@pytest.fixture
def wiki_structure(tmp_path):
    structure = WikiStructure(tmp_path)
    structure.ensure_structure()
    for index in range(20):
        path = structure.base_dir / "raw" / f"doc-{index:02d}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"Document {index}", encoding="utf-8")
    return structure


@pytest.fixture
def mock_indexer():
    return AsyncMock(spec=WikiIndexer)


@pytest.mark.asyncio
async def test_facet_seeds_reach_second_batch_prompt(wiki_structure, mock_indexer) -> None:
    queue = WikiIngestionQueue(wiki_structure)
    pending_paths = [str(wiki_structure.base_dir / "raw" / f"doc-{index:02d}.md") for index in range(6)]
    queue.add_batch(pending_paths)

    captured_human_contents: list[str] = []
    llm = AsyncMock()

    async def _capture_invoke(messages: list) -> AIMessage:
        for message in messages:
            if isinstance(message, HumanMessage):
                captured_human_contents.append(str(message.content))
        return AIMessage(content='[{"name": "Shared Topic", "definition": "A concept reused across batches."}]')

    llm.ainvoke = _capture_invoke

    config = WikiConfig(parallel_compilation=False)
    compile_config = WikiCompileConfig(require_approval=False)
    compiler = WikiCompiler(llm, wiki_structure, config, compile_config, indexer=mock_indexer)
    WikiCompiler._compile_sessions.clear()

    compiler._ensure_compile_session()
    batch_one = queue.get_pending_items(limit=3)
    await compiler._extract_concepts_batch(batch_one)
    batch_two = queue.get_pending_items(limit=3)
    await compiler._extract_concepts_batch(batch_two)

    assert len(captured_human_contents) >= 4
    later_batches = captured_human_contents[3:]
    assert any("Shared Topic" in content and "Facet concept seeds" in content for content in later_batches)
