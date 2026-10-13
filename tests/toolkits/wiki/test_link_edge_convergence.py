"""Wiki graph edges converge when a same-named page appears or disappears."""

from collections.abc import Sequence
from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.wiki.core.config import WikiConfig
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.pipeline.publication import publish_concept_article
from myrm_agent_harness.toolkits.wiki.retrieval.indexer import WikiIndexer


def _article(body: str, aliases: tuple[str, ...] = ()) -> str:
    alias_line = f"aliases: [{', '.join(aliases)}]\n" if aliases else ""
    return f"---\ntype: concept\n{alias_line}---\n## Compiled Truth\n{body}\n\n## Timeline\n- seeded\n"


@pytest.fixture
def structure(tmp_path: Path) -> WikiStructure:
    vault = WikiStructure(tmp_path)
    vault.ensure_structure()
    return vault


@pytest.fixture
def indexer(structure: WikiStructure) -> WikiIndexer:
    return WikiIndexer(structure, WikiConfig(enable_hybrid_search=False))


def _edges(indexer: WikiIndexer) -> set[tuple[str, str]]:
    with indexer._get_conn() as conn:
        return {(str(r["source"]), str(r["target"])) for r in conn.execute("SELECT source, target FROM wiki_edges")}


async def _publish(
    structure: WikiStructure, indexer: WikiIndexer, name: str, body: str = "Body.", **kwargs: tuple[str, ...]
) -> None:
    await publish_concept_article(structure, indexer, name, _article(body, **kwargs))


def _spy_rereads(indexer: WikiIndexer, monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    rereads: list[list[str]] = []
    original = indexer._reread_page_links

    def spy(sources: Sequence[str]) -> None:
        rereads.append(list(sources))
        original(sources)

    monkeypatch.setattr(indexer, "_reread_page_links", spy)
    return rereads


@pytest.mark.asyncio
async def test_a_page_sharing_only_a_file_name_leaves_stored_links_until_their_page_is_written(
    structure: WikiStructure, indexer: WikiIndexer, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _publish(structure, indexer, "A/Overview")
    await _publish(structure, indexer, "Guides/Start", "See [[Overview]].")
    rereads = _spy_rereads(indexer, monkeypatch)

    await _publish(structure, indexer, "B/Overview")

    assert rereads == [[]]
    assert _edges(indexer) == {("guides/start", "a/overview")}

    await _publish(structure, indexer, "Guides/Start", "See [[Overview]].")

    assert _edges(indexer) == {("guides/start", "Overview")}


@pytest.mark.asyncio
async def test_removing_a_page_re_reads_the_links_that_named_it_ahead_of_a_namesake(
    structure: WikiStructure, indexer: WikiIndexer
) -> None:
    await _publish(structure, indexer, "A/Overview")
    await _publish(structure, indexer, "B/Overview")
    await _publish(structure, indexer, "B/Notes", "See [[Overview]].")
    assert _edges(indexer) == {("b/notes", "b/overview")}

    structure.get_concept_file_path("B/Overview").unlink()
    await indexer.delete("b/overview")

    assert _edges(indexer) == {("b/notes", "a/overview")}


@pytest.mark.asyncio
async def test_a_shared_alias_makes_links_ambiguous_and_its_removal_resolves_them_again(
    structure: WikiStructure, indexer: WikiIndexer, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _publish(structure, indexer, "A/First", aliases=("Dup", "Solo"))
    await _publish(structure, indexer, "A/Start", "See [[Dup]] and [[Solo]].")
    assert _edges(indexer) == {("a/start", "a/first")}
    rereads = _spy_rereads(indexer, monkeypatch)

    await _publish(structure, indexer, "B/Second", aliases=("Dup",))

    assert rereads == [["a/start"]]
    assert _edges(indexer) == {("a/start", "Dup"), ("a/start", "a/first")}

    structure.get_concept_file_path("B/Second").unlink()
    await indexer.delete("b/second")

    assert _edges(indexer) == {("a/start", "a/first")}


@pytest.mark.asyncio
async def test_deleting_one_of_two_same_named_pages_resolves_links_to_the_survivor(
    structure: WikiStructure, indexer: WikiIndexer
) -> None:
    await _publish(structure, indexer, "A/Overview")
    await _publish(structure, indexer, "B/Overview")
    await _publish(structure, indexer, "Guides/Start", "See [[Overview]] and [[B/Overview]].")
    assert _edges(indexer) == {("guides/start", "Overview"), ("guides/start", "b/overview")}

    structure.get_concept_file_path("A/Overview").unlink()
    await indexer.delete("a/overview")

    assert _edges(indexer) == {("guides/start", "b/overview")}


@pytest.mark.asyncio
async def test_deleting_a_page_that_shares_no_name_re_reads_no_page(
    structure: WikiStructure, indexer: WikiIndexer, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _publish(structure, indexer, "Guide/Target")
    await _publish(structure, indexer, "Guide/Start", "Read [[Guide/Target]].")
    rereads = _spy_rereads(indexer, monkeypatch)

    structure.get_concept_file_path("Guide/Target").unlink()
    await indexer.delete("guide/target")

    assert rereads == [[]]
    assert _edges(indexer) == {("guide/start", "guide/target")}


@pytest.mark.asyncio
async def test_reindexing_existing_pages_after_a_restart_re_reads_links_for_one_page_at_most(
    structure: WikiStructure, indexer: WikiIndexer, monkeypatch: pytest.MonkeyPatch
) -> None:
    from myrm_agent_harness.toolkits.wiki.retrieval.reindex_vectors import reindex_published_vectors

    for folder in ("A", "B", "C", "D"):
        await _publish(structure, indexer, f"{folder}/Overview", aliases=("Hub",))
        await _publish(structure, indexer, f"{folder}/Start", "See [[A/Overview]].")
    restarted = WikiIndexer(structure, WikiConfig(enable_hybrid_search=False))
    rereads = _spy_rereads(restarted, monkeypatch)

    await reindex_published_vectors(structure, restarted)

    assert len([sources for sources in rereads if sources]) <= 1
