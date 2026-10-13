"""Wiki graph edges: bare file-name links, keyed relinking, page deletion, edge migration."""

import random
import sqlite3
from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.wiki.core.config import WikiConfig
from myrm_agent_harness.toolkits.wiki.core.link_resolver import WikiLinkResolver
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.pipeline.publication import publish_concept_article
from myrm_agent_harness.toolkits.wiki.retrieval.edge_links import relink_dangling_edges
from myrm_agent_harness.toolkits.wiki.retrieval.identity_migration import INDEX_SCHEMA_VERSION
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


@pytest.mark.asyncio
async def test_bare_file_name_links_are_stored_as_edges_to_the_page(
    structure: WikiStructure, indexer: WikiIndexer
) -> None:
    for name in ("Knowledge/Rust/Borrow Checker", "Knowledge/Rust/Lifetimes", "Metrics/metric_gmv_gross"):
        await _publish(structure, indexer, name)

    await _publish(
        structure, indexer, "Guides/Start", "See [[Borrow Checker]], [[lifetimes]], [[metric_gmv_gross]], [[Nobody]]."
    )

    assert _edges(indexer) == {
        ("guides/start", "knowledge/rust/borrow-checker"),
        ("guides/start", "knowledge/rust/lifetimes"),
        ("guides/start", "metrics/metric-gmv-gross"),
        ("guides/start", "Nobody"),
    }


@pytest.mark.asyncio
async def test_bare_link_written_before_its_target_converges_when_the_page_is_published(
    structure: WikiStructure, indexer: WikiIndexer
) -> None:
    await _publish(structure, indexer, "Guides/Start", "Read [[Deep Dive]] next.")
    assert _edges(indexer) == {("guides/start", "Deep Dive")}

    await _publish(structure, indexer, "Guides/Deep Dive")

    assert _edges(indexer) == {("guides/start", "guides/deep-dive")}


@pytest.mark.asyncio
async def test_page_in_the_linking_pages_folder_wins_and_a_shared_name_elsewhere_stays_unresolved(
    structure: WikiStructure, indexer: WikiIndexer
) -> None:
    await _publish(structure, indexer, "Rust/Ownership")
    await _publish(structure, indexer, "Law/Ownership")

    await _publish(structure, indexer, "Rust/Guide", "See [[Ownership]].")
    await _publish(structure, indexer, "Misc/Guide", "See [[Ownership]].")

    assert _edges(indexer) == {("rust/guide", "rust/ownership"), ("misc/guide", "Ownership")}


@pytest.mark.asyncio
async def test_a_page_unrelated_to_unresolved_edges_does_not_re_resolve_them(
    structure: WikiStructure, indexer: WikiIndexer, monkeypatch: pytest.MonkeyPatch
) -> None:
    ghosts = " ".join(f"[[Ghost {n}]]" for n in range(40))
    await _publish(structure, indexer, "Guides/Start", ghosts)
    await _publish(structure, indexer, "Warmup/Page")

    calls: list[str] = []
    original = WikiLinkResolver.resolve

    def counting_resolve(self: WikiLinkResolver, target: str, source: str | None = None) -> str | None:
        calls.append(target)
        return original(self, target, source)

    monkeypatch.setattr(WikiLinkResolver, "resolve", counting_resolve)

    await _publish(structure, indexer, "Misc/Unrelated")
    assert calls == []

    await _publish(structure, indexer, "Misc/Ghost 7")
    assert calls == ["Ghost 7"]
    assert ("guides/start", "misc/ghost-7") in _edges(indexer)


@pytest.mark.asyncio
async def test_aliases_beyond_one_lookup_chunk_still_find_their_edges(
    structure: WikiStructure, indexer: WikiIndexer
) -> None:
    aliases = tuple(f"Alias{n:03d}" for n in range(450))
    await _publish(structure, indexer, "Guides/Start", "See [[Alias449]] and [[Alias000]].")

    await _publish(structure, indexer, "Guides/Hub", aliases=aliases)

    assert _edges(indexer) == {("guides/start", "guides/hub")}


@pytest.mark.asyncio
@pytest.mark.parametrize("seed", [1, 2, 3])
async def test_keyed_relinking_leaves_nothing_a_full_relink_would_resolve(
    structure: WikiStructure, indexer: WikiIndexer, seed: int
) -> None:
    rng = random.Random(seed)
    folders = ("rust", "law", "misc")
    names = [f"Topic {n}" for n in range(24)]
    pages = [(f"{rng.choice(folders)}/{name}", f"Nick {n}") for n, name in enumerate(names)]
    spellings = [*names, *(f"Nick {n}" for n in range(24)), *(page for page, _ in pages), "Missing", "Topic"]
    rng.shuffle(pages)

    for page, alias in pages:
        links = " ".join(f"[[{rng.choice(spellings)}]]" for _ in range(6))
        await _publish(structure, indexer, page, links, aliases=(alias,))

    with indexer._get_conn() as conn:
        assert relink_dangling_edges(conn, WikiLinkResolver(structure)) == 0


@pytest.mark.asyncio
async def test_inbound_edges_survive_page_deletion_and_reconnect_when_the_page_returns(
    structure: WikiStructure, indexer: WikiIndexer
) -> None:
    await _publish(structure, indexer, "Guide/Target")
    await _publish(structure, indexer, "Guide/Start", "Read [[Guide/Target]].")
    assert indexer.get_knowledge_graph()["edges"]

    structure.get_concept_file_path("Guide/Target").unlink()
    await indexer.delete("guide/target")

    assert _edges(indexer) == {("guide/start", "guide/target")}
    assert indexer.get_knowledge_graph()["edges"] == []
    assert indexer.graph_insights()["unexpected_connections"] == []
    outlinks = indexer.get_concept_links("guide/start")["outlinks"]
    assert [(link["name"], link["exists"]) for link in outlinks] == [("guide/target", False)]

    await _publish(structure, indexer, "Guide/Target")

    assert len(indexer.get_knowledge_graph()["edges"]) == 1
    outlinks = indexer.get_concept_links("guide/start")["outlinks"]
    assert [(link["name"], link["exists"]) for link in outlinks] == [("guide/target", True)]


@pytest.mark.asyncio
async def test_deleting_a_page_removes_its_own_outgoing_edges(structure: WikiStructure, indexer: WikiIndexer) -> None:
    await _publish(structure, indexer, "Guide/Target")
    await _publish(structure, indexer, "Guide/Start", "Read [[Guide/Target]].")

    await indexer.delete("guide/start")

    assert _edges(indexer) == set()


def _legacy_index(structure: WikiStructure, version: int, rows: list[tuple[str, str, float]]) -> None:
    """An index whose edge table predates the stored target spellings."""
    conn = sqlite3.connect(structure.base_dir / ".wiki_index.db")
    conn.execute(
        "CREATE TABLE wiki_edges(source TEXT, target TEXT, weight REAL DEFAULT 1.0, PRIMARY KEY (source, target))"
    )
    conn.executemany("INSERT INTO wiki_edges (source, target, weight) VALUES (?, ?, ?)", rows)
    conn.execute(f"PRAGMA user_version = {version}")
    conn.commit()
    conn.close()


def _columns(indexer: WikiIndexer) -> set[str]:
    with indexer._get_conn() as conn:
        return {str(row["name"]) for row in conn.execute("PRAGMA table_info(wiki_edges)")}


def test_legacy_edge_table_gains_target_spellings_and_unresolved_bare_links_converge(structure: WikiStructure) -> None:
    for name in ("Knowledge/Rust/Ownership", "Guides/Start"):
        structure.get_concept_file_path(name).write_text(_article("Body."), encoding="utf-8")
    _legacy_index(
        structure,
        version=1,
        rows=[("guides/start", "Ownership", 3.0), ("guides/start", "system:crm", 3.0), ("guides/start", "Gone", 3.0)],
    )

    migrated = WikiIndexer(structure, WikiConfig(enable_hybrid_search=False))

    assert {"target_key", "target_slug"} <= _columns(migrated)
    assert _edges(migrated) == {
        ("guides/start", "knowledge/rust/ownership"),
        ("guides/start", "system:crm"),
        ("guides/start", "Gone"),
    }
    with migrated._get_conn() as conn:
        forms = {
            str(r["target"]): (r["target_key"], r["target_slug"])
            for r in conn.execute("SELECT target, target_key, target_slug FROM wiki_edges")
        }
        assert int(conn.execute("PRAGMA user_version").fetchone()[0]) == INDEX_SCHEMA_VERSION
    assert forms["system:crm"] == ("", "")
    assert forms["Gone"] == ("gone", "gone")
    assert forms["knowledge/rust/ownership"] == ("knowledge/rust/ownership", "knowledge/rust/ownership")


def test_migrated_edge_table_is_not_converged_again(structure: WikiStructure) -> None:
    structure.get_concept_file_path("Knowledge/Rust/Ownership").write_text(_article("Body."), encoding="utf-8")
    _legacy_index(structure, version=INDEX_SCHEMA_VERSION, rows=[("guides/start", "Ownership", 3.0)])

    untouched = WikiIndexer(structure, WikiConfig(enable_hybrid_search=False))

    assert _edges(untouched) == {("guides/start", "Ownership")}
