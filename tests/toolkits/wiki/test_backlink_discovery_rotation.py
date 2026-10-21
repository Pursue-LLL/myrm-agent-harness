"""LLM backlink discovery rotation: every page gets its turn, and only a real answer advances the cursor."""

from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.wiki import WikiStructure
from myrm_agent_harness.toolkits.wiki.core.claims_contract import read_wiki_metadata_file
from myrm_agent_harness.toolkits.wiki.maintenance import backlink_discovery
from myrm_agent_harness.toolkits.wiki.pipeline.postprocess import save_metadata
from tests.toolkits.wiki.discovery_support import CURSOR_KEY, ScriptedLLM, make_linter, write_page


@pytest.fixture
def structure(tmp_path: Path) -> WikiStructure:
    wiki = WikiStructure(tmp_path / "wiki-root")
    wiki.ensure_structure()
    return wiki


@pytest.mark.asyncio
async def test_every_page_gets_its_turn_across_runs(structure: WikiStructure) -> None:
    keys = [f"page-{index:02d}" for index in range(30)]
    for key in keys:
        write_page(structure, key)
    llm = ScriptedLLM("[]")
    linter = make_linter(llm, structure)

    await linter._discover_connections()
    first = llm.articles()
    cursor = read_wiki_metadata_file(structure.get_wiki_metadata_path())[CURSOR_KEY]
    llm.prompts.clear()
    await linter._discover_connections()
    second = llm.articles()

    assert first == keys[:20]
    assert cursor == "page-19"
    assert second == keys[20:] + keys[:10]
    assert set(first) | set(second) == set(keys)


@pytest.mark.asyncio
async def test_small_vault_runs_everything_and_keeps_no_cursor(structure: WikiStructure) -> None:
    for index in range(5):
        write_page(structure, f"page-{index}")
    llm = ScriptedLLM("[]")

    await make_linter(llm, structure)._discover_connections()

    assert sorted(llm.articles()) == [f"page-{index}" for index in range(5)]
    assert CURSOR_KEY not in read_wiki_metadata_file(structure.get_wiki_metadata_path())


@pytest.mark.asyncio
async def test_cursor_survives_the_next_compile_metadata_save(structure: WikiStructure) -> None:
    for index in range(25):
        write_page(structure, f"page-{index:02d}")
    await make_linter(ScriptedLLM("[]"), structure)._discover_connections()

    await save_metadata(structure, concepts_count=25, articles_count=25)

    metadata = read_wiki_metadata_file(structure.get_wiki_metadata_path())
    assert metadata[CURSOR_KEY] == "page-19"
    assert metadata["total_concepts"] == 25


@pytest.mark.asyncio
async def test_a_model_outage_does_not_use_up_the_rotation(structure: WikiStructure) -> None:
    for index in range(25):
        write_page(structure, f"page-{index:02d}")

    def _down(_prompt: str) -> None:
        raise RuntimeError("llm unavailable")

    count = await make_linter(ScriptedLLM("[]", on_call=_down), structure)._discover_connections()

    assert count == 0
    assert CURSOR_KEY not in read_wiki_metadata_file(structure.get_wiki_metadata_path())


@pytest.mark.asyncio
async def test_pages_that_cannot_take_a_link_do_not_hold_the_rotation(structure: WikiStructure) -> None:
    for index in range(25):
        key = f"page-{index:02d}"
        structure.get_concept_file_path(key).write_text(f"# {key}\nNo frontmatter.\n", encoding="utf-8")
    llm = ScriptedLLM('["page-24"]')

    count = await make_linter(llm, structure)._discover_connections()

    assert count == 0
    assert read_wiki_metadata_file(structure.get_wiki_metadata_path())[CURSOR_KEY] == "page-19"


@pytest.mark.asyncio
async def test_a_cursor_that_cannot_be_saved_does_not_fail_the_run(
    structure: WikiStructure, monkeypatch: pytest.MonkeyPatch
) -> None:
    for index in range(25):
        write_page(structure, f"page-{index:02d}")

    def _disk_full(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(backlink_discovery, "write_wiki_metadata_merge", _disk_full)
    llm = ScriptedLLM(lambda prompt: '["page-24"]' if "## Article: page-00\n" in prompt else "[]")

    count = await make_linter(llm, structure)._discover_connections()

    assert count == 1
    assert CURSOR_KEY not in read_wiki_metadata_file(structure.get_wiki_metadata_path())
