"""End-to-end verification of primary_namespace isolation on embedded Qdrant.

Unit tests mock the vector store and only assert filter *structure*. This module
drives a real in-memory Qdrant instance to prove the matching behavior the P0
cross-agent isolation fix relies on:

- A memory whose single-value ``primary_namespace`` is agent A is never returned
  by agent B's scope query, even though both agents broadcast the same ``global``
  namespace inside the multi-value ``namespaces`` list.
- Shared memories (``primary_namespace == "global"``) stay readable by every agent.
- ``{"id": {"$in": [...]}}`` point-ID filtering narrows results as designed.
"""

import pytest

from myrm_agent_harness.toolkits.vector.base import VectorDocument
from myrm_agent_harness.toolkits.vector.qdrant.factory import (
    clear_embedded_stores,
    create_embedded_store,
)

DIM = 8
_EMBEDDED_VECTOR = [0.1] * DIM


def _doc(point_id: str, *, primary: str, namespaces: list[str], content: str) -> VectorDocument:
    return VectorDocument(
        id=point_id,
        content=content,
        vector=_EMBEDDED_VECTOR,
        metadata={
            "archived": False,
            "primary_namespace": primary,
            "namespaces": namespaces,
        },
    )


@pytest.fixture
async def embedded_store():
    # The embedded factory caches stores per path; clear first so a previously
    # closed :memory: instance is never reused.
    await clear_embedded_stores()
    store = await create_embedded_store(path=":memory:")
    try:
        yield store
    finally:
        await store.close()
        await clear_embedded_stores()


@pytest.mark.asyncio
async def test_cross_agent_private_memory_is_not_leaked(embedded_store) -> None:
    await embedded_store.create_collection("mem_iso", dimension=DIM, distance="cosine")
    await embedded_store.upsert(
        "mem_iso",
        [
            _doc("a", primary="agent:A", namespaces=["global", "agent:A"], content="A private"),
            _doc("b", primary="agent:B", namespaces=["global", "agent:B"], content="B private"),
            _doc("g", primary="global", namespaces=["global"], content="shared"),
        ],
    )

    agent_a_results = await embedded_store.search(
        "mem_iso",
        _EMBEDDED_VECTOR,
        limit=10,
        filters={"archived": False, "primary_namespace": ["global", "agent:A"]},
    )
    agent_a_contents = {r.document.content for r in agent_a_results}
    assert "A private" in agent_a_contents
    assert "shared" in agent_a_contents
    assert "B private" not in agent_a_contents

    agent_b_results = await embedded_store.search(
        "mem_iso",
        _EMBEDDED_VECTOR,
        limit=10,
        filters={"archived": False, "primary_namespace": ["global", "agent:B"]},
    )
    agent_b_contents = {r.document.content for r in agent_b_results}
    assert "B private" in agent_b_contents
    assert "shared" in agent_b_contents
    assert "A private" not in agent_b_contents  # A's private memory must never surface for B


@pytest.mark.asyncio
async def test_has_id_filter_narrows_results(embedded_store) -> None:
    await embedded_store.create_collection("mem_ids", dimension=DIM, distance="cosine")
    await embedded_store.upsert(
        "mem_ids",
        [
            _doc("p1", primary="global", namespaces=["global"], content="one"),
            _doc("p2", primary="global", namespaces=["global"], content="two"),
        ],
    )

    # Point IDs are deterministically re-keyed to UUIDs on upsert; resolve the
    # real point ID first, mirroring how pass1 results feed the pass2 filter.
    all_results = await embedded_store.search(
        "mem_ids",
        _EMBEDDED_VECTOR,
        limit=10,
        filters={"primary_namespace": ["global"]},
    )
    p1_point_id = next(r.document.id for r in all_results if r.document.content == "one")

    results = await embedded_store.search(
        "mem_ids",
        _EMBEDDED_VECTOR,
        limit=10,
        filters={"primary_namespace": ["global"], "id": {"$in": [p1_point_id]}},
    )
    assert {r.document.id for r in results} == {p1_point_id}


@pytest.mark.asyncio
async def test_id_list_filter_narrows_results(embedded_store) -> None:
    await embedded_store.create_collection("mem_ids_list", dimension=DIM, distance="cosine")
    await embedded_store.upsert(
        "mem_ids_list",
        [
            _doc("q1", primary="global", namespaces=["global"], content="one"),
            _doc("q2", primary="global", namespaces=["global"], content="two"),
        ],
    )

    # List-value IN syntax must behave identically to the ``$in`` dict form
    # (FilterDict documents IN as ``{"key": [val1, val2]}``).
    all_results = await embedded_store.search(
        "mem_ids_list",
        _EMBEDDED_VECTOR,
        limit=10,
        filters={"primary_namespace": ["global"]},
    )
    q1_point_id = next(r.document.id for r in all_results if r.document.content == "one")

    results = await embedded_store.search(
        "mem_ids_list",
        _EMBEDDED_VECTOR,
        limit=10,
        filters={"primary_namespace": ["global"], "id": [q1_point_id]},
    )
    assert {r.document.id for r in results} == {q1_point_id}


@pytest.mark.asyncio
async def test_id_scalar_filter_narrows_results(embedded_store) -> None:
    await embedded_store.create_collection("mem_ids_scalar", dimension=DIM, distance="cosine")
    await embedded_store.upsert(
        "mem_ids_scalar",
        [
            _doc("q1", primary="global", namespaces=["global"], content="one"),
            _doc("q2", primary="global", namespaces=["global"], content="two"),
        ],
    )

    all_results = await embedded_store.search(
        "mem_ids_scalar",
        _EMBEDDED_VECTOR,
        limit=10,
        filters={"primary_namespace": ["global"]},
    )
    q1_point_id = next(r.document.id for r in all_results if r.document.content == "one")

    # Scalar (single-value) ``id`` must behave identically to the list form —
    # both map to a point-id filter, never to a payload ``id`` field.
    results = await embedded_store.search(
        "mem_ids_scalar",
        _EMBEDDED_VECTOR,
        limit=10,
        filters={"primary_namespace": ["global"], "id": q1_point_id},
    )
    assert {r.document.id for r in results} == {q1_point_id}


@pytest.mark.asyncio
async def test_empty_id_set_returns_zero_without_crash(embedded_store) -> None:
    await embedded_store.create_collection("mem_ids_empty", dimension=DIM, distance="cosine")
    await embedded_store.upsert(
        "mem_ids_empty",
        [_doc("e1", primary="global", namespaces=["global"], content="one")],
    )

    # Empty ``$in`` / list-value ID queries build an empty HasIdCondition; the
    # live backend must treat them as an empty point-id set (0 matches) for
    # search and count alike, never raising.
    results = await embedded_store.search(
        "mem_ids_empty",
        _EMBEDDED_VECTOR,
        limit=10,
        filters={"primary_namespace": ["global"], "id": {"$in": []}},
    )
    assert results == []

    results = await embedded_store.search(
        "mem_ids_empty",
        _EMBEDDED_VECTOR,
        limit=10,
        filters={"primary_namespace": ["global"], "id": []},
    )
    assert results == []

    assert await embedded_store.count("mem_ids_empty", filters={"primary_namespace": ["global"], "id": []}) == 0


@pytest.mark.asyncio
async def test_delete_by_id_filter_removes_only_target(embedded_store) -> None:
    await embedded_store.create_collection("mem_ids_delete", dimension=DIM, distance="cosine")
    await embedded_store.upsert(
        "mem_ids_delete",
        [
            _doc("d1", primary="global", namespaces=["global"], content="one"),
            _doc("d2", primary="global", namespaces=["global"], content="two"),
        ],
    )

    all_results = await embedded_store.search(
        "mem_ids_delete",
        _EMBEDDED_VECTOR,
        limit=10,
        filters={"primary_namespace": ["global"]},
    )
    d1_point_id = next(r.document.id for r in all_results if r.document.content == "one")

    # ID-filtered deletion must reach the same HasIdCondition path as search and
    # remove only the targeted point, leaving the sibling untouched.
    deleted = await embedded_store.delete_by_filter("mem_ids_delete", {"id": [d1_point_id]})
    assert deleted == 1

    remaining = await embedded_store.search(
        "mem_ids_delete",
        _EMBEDDED_VECTOR,
        limit=10,
        filters={"primary_namespace": ["global"]},
    )
    assert {r.document.content for r in remaining} == {"two"}
