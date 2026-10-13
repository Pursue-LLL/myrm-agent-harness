"""Wiki index identity: one index row per concept page, edges stored as page keys."""

from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.wiki.core.config import WikiConfig
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.pipeline.publication import publish_concept_article
from myrm_agent_harness.toolkits.wiki.retrieval.identity_migration import CONCEPT_KEY_SCHEMA_VERSION
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


def _fts_names(indexer: WikiIndexer) -> list[str]:
    with indexer._get_conn() as conn:
        return sorted(str(row["concept_name"]) for row in conn.execute("SELECT concept_name FROM wiki_fts"))


def _edges(indexer: WikiIndexer) -> set[tuple[str, str]]:
    with indexer._get_conn() as conn:
        return {(str(r["source"]), str(r["target"])) for r in conn.execute("SELECT source, target FROM wiki_edges")}


async def _publish_compiled_set(structure: WikiStructure, indexer: WikiIndexer) -> None:
    await publish_concept_article(
        structure,
        indexer,
        "Programming/Rust/Ownership",
        _article("See [[Borrow Checker]], [[Programming/Rust/Lifetimes]] and [[Missing Thing]]."),
    )
    await publish_concept_article(structure, indexer, "Programming/Rust/Lifetimes", _article("Lifetimes."))
    await publish_concept_article(
        structure, indexer, "Programming/Rust/Borrow Checker", _article("Checker.", aliases=("Borrow Checker",))
    )


@pytest.mark.asyncio
async def test_compile_and_maintenance_publishing_share_one_index_row_per_page(
    structure: WikiStructure, indexer: WikiIndexer
) -> None:
    await _publish_compiled_set(structure, indexer)
    for page in structure.list_concepts():
        rel = str(page.relative_to(structure.concepts_dir).with_suffix("")).replace("\\", "/")
        await publish_concept_article(structure, indexer, rel, page.read_text(encoding="utf-8"))

    expected = ["programming/rust/borrow-checker", "programming/rust/lifetimes", "programming/rust/ownership"]
    assert _fts_names(indexer) == expected
    assert sorted(node["id"] for node in indexer.get_knowledge_graph()["nodes"]) == expected


@pytest.mark.asyncio
async def test_edge_targets_are_stored_as_page_keys_for_path_alias_and_unknown_links(
    structure: WikiStructure, indexer: WikiIndexer
) -> None:
    await _publish_compiled_set(structure, indexer)

    assert _edges(indexer) == {
        ("programming/rust/ownership", "programming/rust/borrow-checker"),
        ("programming/rust/ownership", "programming/rust/lifetimes"),
        ("programming/rust/ownership", "Missing Thing"),
    }
    graph = indexer.get_knowledge_graph()
    assert len(graph["edges"]) == 2
    isolated = {gap["node"] for gap in indexer.graph_insights()["knowledge_gaps"] if gap["type"] == "isolated"}
    assert "programming/rust/ownership" not in isolated


@pytest.mark.asyncio
async def test_link_written_before_its_target_page_converges_when_the_target_is_published(
    structure: WikiStructure, indexer: WikiIndexer
) -> None:
    await publish_concept_article(structure, indexer, "Guide/Start", _article("Read [[Deep Dive]] next."))
    assert _edges(indexer) == {("guide/start", "Deep Dive")}

    await publish_concept_article(structure, indexer, "Guide/Details", _article("Details.", aliases=("Deep Dive",)))

    assert _edges(indexer) == {("guide/start", "guide/details")}


@pytest.mark.asyncio
async def test_alias_added_later_relinks_existing_dangling_edges(
    structure: WikiStructure, indexer: WikiIndexer
) -> None:
    await publish_concept_article(structure, indexer, "Guide/Start", _article("Read [[Nickname]]."))
    await publish_concept_article(structure, indexer, "Guide/Target", _article("Target."))
    assert ("guide/start", "Nickname") in _edges(indexer)

    await publish_concept_article(structure, indexer, "Guide/Target", _article("Target.", aliases=("Nickname",)))

    assert _edges(indexer) == {("guide/start", "guide/target")}


@pytest.mark.asyncio
async def test_link_to_own_alias_creates_no_self_edge(structure: WikiStructure, indexer: WikiIndexer) -> None:
    await publish_concept_article(
        structure, indexer, "Topic/Self", _article("Also known as [[Selfie]].", aliases=("Selfie",))
    )
    assert _edges(indexer) == set()


@pytest.mark.asyncio
async def test_markdown_link_resolves_relative_to_the_linking_page(
    structure: WikiStructure, indexer: WikiIndexer
) -> None:
    await publish_concept_article(structure, indexer, "Docs/Sibling", _article("Sibling."))
    await publish_concept_article(structure, indexer, "Docs/Main", _article("Go to [sibling](sibling.md)."))

    assert _edges(indexer) == {("docs/main", "docs/sibling")}


@pytest.mark.asyncio
async def test_delete_removes_the_page_under_compile_name_and_path(
    structure: WikiStructure, indexer: WikiIndexer
) -> None:
    await _publish_compiled_set(structure, indexer)

    await indexer.delete("Programming/Rust/Ownership")
    assert "programming/rust/ownership" not in _fts_names(indexer)
    assert not {edge for edge in _edges(indexer) if "programming/rust/ownership" in edge}

    await indexer.delete("programming/rust/lifetimes")
    assert _fts_names(indexer) == ["programming/rust/borrow-checker"]


@pytest.mark.asyncio
async def test_concept_links_lookup_accepts_compile_name_and_page_path(
    structure: WikiStructure, indexer: WikiIndexer
) -> None:
    await _publish_compiled_set(structure, indexer)

    by_compile_name = indexer.get_concept_links("Programming/Rust/Ownership")
    by_path = indexer.get_concept_links("programming/rust/ownership")

    assert by_compile_name["concept_name"] == by_path["concept_name"] == "programming/rust/ownership"
    assert {link["name"] for link in by_compile_name["outlinks"]} == {link["name"] for link in by_path["outlinks"]}
    assert "programming/rust/lifetimes" in {link["name"] for link in by_path["outlinks"]}
    backlinks = indexer.get_concept_links("Programming/Rust/Lifetimes")["backlinks"]
    assert [link["name"] for link in backlinks] == ["programming/rust/ownership"]


def _stamp_legacy(indexer: WikiIndexer) -> None:
    with indexer._get_conn() as conn:
        conn.execute("PRAGMA user_version = 0")


def _insert_row(indexer: WikiIndexer, name: str) -> None:
    with indexer._get_conn() as conn:
        conn.execute(
            "INSERT INTO wiki_fts (concept_name, truth_content, search_terms) VALUES (?, ?, ?)", (name, name, name)
        )
        conn.execute(
            "INSERT OR REPLACE INTO wiki_index_meta (concept_name, publish_status) VALUES (?, 'published')", (name,)
        )


def _user_version(indexer: WikiIndexer) -> int:
    with indexer._get_conn() as conn:
        return int(conn.execute("PRAGMA user_version").fetchone()[0])


def test_legacy_index_rows_are_merged_into_page_identities_once(structure: WikiStructure) -> None:
    structure.get_concept_file_path("Knowledge/X/Y").write_text(_article("y body"), encoding="utf-8")
    structure.get_concept_file_path("Knowledge/X/Z").write_text(
        _article("z body", aliases=("Why Alias",)), encoding="utf-8"
    )
    seeded = WikiIndexer(structure, WikiConfig(enable_hybrid_search=False))
    assert _user_version(seeded) == CONCEPT_KEY_SCHEMA_VERSION

    # Legacy state: compile-name rows next to path rows, an orphan row, edges using both spellings.
    _stamp_legacy(seeded)
    for legacy in ("Knowledge/X/Y", "Knowledge/X/Z", "knowledge/x/z", "Opaque Name"):
        _insert_row(seeded, legacy)
    seeded.upsert_edges("Knowledge/X/Y", ["Why Alias", "Opaque Name"])
    seeded.upsert_edges("Opaque Name", ["Knowledge/X/Y"])

    migrated = WikiIndexer(structure, WikiConfig(enable_hybrid_search=False))

    assert _fts_names(migrated) == ["Opaque Name", "knowledge/x/y", "knowledge/x/z"]
    assert _edges(migrated) == {
        ("knowledge/x/y", "knowledge/x/z"),
        ("knowledge/x/y", "Opaque Name"),
        ("Opaque Name", "knowledge/x/y"),
    }
    assert _user_version(migrated) == CONCEPT_KEY_SCHEMA_VERSION

    # A migrated index is never rewritten again.
    _insert_row(migrated, "Knowledge/Later")
    structure.get_concept_file_path("Knowledge/Later").write_text(_article("later"), encoding="utf-8")
    assert "Knowledge/Later" in _fts_names(WikiIndexer(structure, WikiConfig(enable_hybrid_search=False)))
