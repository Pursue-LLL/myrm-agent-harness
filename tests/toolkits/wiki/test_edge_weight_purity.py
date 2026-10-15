"""Edge weight is a pure function of the stored edges, whatever order the pages were written in."""

import itertools
import random
import sqlite3
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.wiki.core.config import WikiConfig
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.pipeline.publication import publish_concept_article
from myrm_agent_harness.toolkits.wiki.retrieval.identity_migration import INDEX_SCHEMA_VERSION
from myrm_agent_harness.toolkits.wiki.retrieval.indexer import WikiIndexer

Weights = dict[tuple[str, str], float]

TRIAD = {"Guides/A": ["Guides/B", "Guides/C"], "Guides/B": ["Guides/C"], "Guides/C": []}


def _article(links: Sequence[str], aliases: Sequence[str] = ()) -> str:
    body = " ".join(f"[[{link}]]" for link in links) or "Body."
    alias_line = f"aliases: [{', '.join(aliases)}]\n" if aliases else ""
    return f"---\ntype: concept\n{alias_line}---\n## Compiled Truth\n{body}\n\n## Timeline\n- seeded\n"


def _open(root: Path) -> tuple[WikiStructure, WikiIndexer]:
    structure = WikiStructure(root)
    structure.ensure_structure()
    return structure, WikiIndexer(structure, WikiConfig(enable_hybrid_search=False))


async def _write(structure: WikiStructure, indexer: WikiIndexer, name: str, links: Sequence[str]) -> None:
    await publish_concept_article(structure, indexer, name, _article(links))


async def _build(root: Path, pages: dict[str, list[str]], order: Sequence[str]) -> WikiIndexer:
    structure, indexer = _open(root)
    for name in order:
        await _write(structure, indexer, name, pages[name])
    return indexer


def _stored(indexer: WikiIndexer) -> Weights:
    with indexer._get_conn() as conn:
        return {(str(r["source"]), str(r["target"])): float(r["weight"]) for r in _edge_rows(conn)}


def _edge_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT source, target, weight FROM wiki_edges").fetchall()


def _derived(edges: Weights) -> Weights:
    """Weights recomputed from scratch: 3.0 per direct link, +0.5 per link both ends share, capped at 1.5."""
    out: dict[str, set[str]] = defaultdict(set)
    for source, target in edges:
        out[source].add(target)
    return {(s, t): round(3.0 + min(1.5, 0.5 * len(out[s] & out[t])), 2) for s, t in edges}


def _assert_pure(indexer: WikiIndexer) -> Weights:
    stored = _stored(indexer)
    assert stored == _derived(stored)
    return stored


@pytest.mark.asyncio
@pytest.mark.parametrize("order", list(itertools.permutations(TRIAD)))
async def test_triad_weights_do_not_depend_on_write_order(tmp_path: Path, order: tuple[str, ...]) -> None:
    indexer = await _build(tmp_path, TRIAD, order)

    assert _assert_pure(indexer) == {
        ("guides/a", "guides/b"): 3.5,
        ("guides/a", "guides/c"): 3.0,
        ("guides/b", "guides/c"): 3.0,
    }


@pytest.mark.parametrize("order", [("A", "B", "C"), ("C", "B", "A"), ("B", "C", "A")])
def test_upsert_edges_weights_do_not_depend_on_call_order(tmp_path: Path, order: tuple[str, ...]) -> None:
    _, indexer = _open(tmp_path)
    links = {"A": ["B", "C"], "B": ["C"], "C": []}

    for source in order:
        indexer.upsert_edges(source, links[source])

    assert _assert_pure(indexer) == {("A", "B"): 3.5, ("A", "C"): 3.0, ("B", "C"): 3.0}


@pytest.mark.asyncio
@pytest.mark.parametrize("seed", [1, 2, 3, 4])
async def test_random_graph_weights_are_identical_for_any_write_order(tmp_path: Path, seed: int) -> None:
    rng = random.Random(seed)
    names = [f"Topics/Page {n}" for n in range(14)]
    pages = {name: rng.sample([*names, "Topics/Missing", "Topics/Absent"], k=rng.randint(0, 6)) for name in names}
    shuffled = list(names)
    rng.shuffle(shuffled)

    results = [
        _assert_pure(await _build(tmp_path / f"order{n}", pages, order))
        for n, order in enumerate((names, names[::-1], shuffled))
    ]

    assert results[0] == results[1] == results[2]
    assert any(weight > 3.0 for weight in results[0].values())


@pytest.mark.asyncio
async def test_editing_a_page_refreshes_the_edges_that_point_at_it(tmp_path: Path) -> None:
    structure, indexer = _open(tmp_path)
    for name in ("Guides/C", "Guides/B"):
        await _write(structure, indexer, name, [])
    await _write(structure, indexer, "Guides/A", ["Guides/B", "Guides/C"])
    assert _assert_pure(indexer)[("guides/a", "guides/b")] == 3.0

    await _write(structure, indexer, "Guides/B", ["Guides/C"])
    assert _assert_pure(indexer)[("guides/a", "guides/b")] == 3.5

    await _write(structure, indexer, "Guides/B", [])
    assert _assert_pure(indexer)[("guides/a", "guides/b")] == 3.0


@pytest.mark.asyncio
async def test_deleting_a_page_refreshes_the_edges_that_point_at_it(tmp_path: Path) -> None:
    indexer = await _build(tmp_path, TRIAD, list(TRIAD))
    structure = indexer._structure
    assert _stored(indexer)[("guides/a", "guides/b")] == 3.5

    structure.get_concept_file_path("Guides/B").unlink()
    await indexer.delete("guides/b")

    assert _assert_pure(indexer)[("guides/a", "guides/b")] == 3.0


@pytest.mark.asyncio
async def test_relinking_a_forward_reference_refreshes_the_rewritten_edges(tmp_path: Path) -> None:
    structure, indexer = _open(tmp_path)
    await _write(structure, indexer, "Guides/C", [])
    await _write(structure, indexer, "Guides/Start", ["Nick B", "Guides/C"])
    assert _assert_pure(indexer)[("guides/start", "Nick B")] == 3.0

    await publish_concept_article(structure, indexer, "Guides/B", _article(["Guides/C"], aliases=["Nick B"]))

    stored = _assert_pure(indexer)
    assert ("guides/start", "Nick B") not in stored
    assert stored[("guides/start", "guides/b")] == 3.5


def test_opening_an_index_from_before_derived_weights_recomputes_them(tmp_path: Path) -> None:
    structure, seeded = _open(tmp_path)
    for source, targets in TRIAD.items():
        seeded.upsert_edges(source, targets)
    with seeded._get_conn() as conn:
        conn.execute("UPDATE wiki_edges SET weight = 9.0")
        conn.execute("PRAGMA user_version = 2")

    reopened = WikiIndexer(structure, WikiConfig(enable_hybrid_search=False))

    assert _assert_pure(reopened) == {
        ("Guides/A", "Guides/B"): 3.5,
        ("Guides/A", "Guides/C"): 3.0,
        ("Guides/B", "Guides/C"): 3.0,
    }
    with reopened._get_conn() as conn:
        assert int(conn.execute("PRAGMA user_version").fetchone()[0]) == INDEX_SCHEMA_VERSION


def test_an_index_at_the_current_version_keeps_its_weights(tmp_path: Path) -> None:
    structure, seeded = _open(tmp_path)
    seeded.upsert_edges("A", ["B"])
    with seeded._get_conn() as conn:
        conn.execute("UPDATE wiki_edges SET weight = 9.0")

    reopened = WikiIndexer(structure, WikiConfig(enable_hybrid_search=False))

    assert _stored(reopened) == {("A", "B"): 9.0}


def test_outgoing_edges_of_equal_weight_come_back_in_name_order(tmp_path: Path) -> None:
    _, indexer = _open(tmp_path)

    indexer.upsert_edges("hub", ["zeta", "mid", "alpha"])

    assert indexer.get_outgoing_edges("hub") == [("alpha", 3.0), ("mid", 3.0), ("zeta", 3.0)]


def test_refreshing_more_pages_than_one_query_binds_still_covers_every_edge(tmp_path: Path) -> None:
    from myrm_agent_harness.toolkits.wiki.retrieval.edge_weights import refresh_edge_weights

    _, indexer = _open(tmp_path)
    hubs = [f"hub{n:03d}" for n in range(450)]
    for hub in hubs:
        indexer.upsert_edges(hub, ["shared-a", "shared-b"])
    indexer.upsert_edges("shared-a", ["shared-b"])
    indexer.upsert_edges("shared-b", ["shared-a"])
    with indexer._get_conn() as conn:
        conn.execute("UPDATE wiki_edges SET weight = 9.0")
        refresh_edge_weights(conn, hubs)

    stored = _stored(indexer)

    assert all(stored[(hub, target)] == 3.5 for hub in hubs for target in ("shared-a", "shared-b"))
    assert stored[("shared-a", "shared-b")] == 9.0, "edges that touch no refreshed page are left alone"
