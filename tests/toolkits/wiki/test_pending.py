from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.toolkits.wiki.core.frontmatter_contract import PUBLISH_STATUS_KEY, WikiPublishStatus
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.pipeline.pending import WikiPendingEditsManager
from myrm_agent_harness.toolkits.wiki.pipeline.publication import StalePendingApprovalError
from myrm_agent_harness.toolkits.wiki.retrieval.indexer import WikiIndexer
from myrm_agent_harness.utils.markdown_frontmatter import parse_frontmatter

_VALID_DRAFT = "---\ntype: concept\n---\n\n## Compiled Truth\nApproved content.\n"
_VALID_EDITED = "---\ntype: concept\n---\n\n## Compiled Truth\nUser-edited final version.\n"


@pytest.fixture
def wiki_structure(tmp_path):
    structure = WikiStructure(tmp_path)
    structure.ensure_structure()
    return structure


@pytest.fixture
def mock_indexer():
    indexer = AsyncMock(spec=WikiIndexer)
    indexer.upsert = AsyncMock()
    indexer.extract_and_upsert_edges = AsyncMock()
    return indexer


def test_wiki_pending_edits_add_and_list(wiki_structure):
    mgr = WikiPendingEditsManager(wiki_structure)
    mgr.add_pending_edit("Test Concept", _VALID_DRAFT)

    edits = mgr.get_pending_edits()
    assert len(edits) == 1
    assert edits[0]["concept_name"] == "Test Concept"
    assert edits[0]["proposed_content"] == _VALID_DRAFT
    assert edits[0]["status"] == "pending"


@pytest.mark.asyncio
async def test_wiki_pending_edits_approve(wiki_structure, mock_indexer):
    mgr = WikiPendingEditsManager(wiki_structure, indexer=mock_indexer)
    mgr.add_pending_edit("Test Concept", _VALID_DRAFT)

    edits = mgr.get_pending_edits()
    edit_id = edits[0]["id"]

    success = await mgr.approve_edit(edit_id)
    assert success is True

    article_path = wiki_structure.get_concept_file_path("Test Concept")
    assert article_path.exists()
    metadata, body = parse_frontmatter(article_path.read_text(encoding="utf-8"))
    assert metadata[PUBLISH_STATUS_KEY] == WikiPublishStatus.PUBLISHED.value
    assert "Approved content." in body

    mock_indexer.upsert.assert_awaited_once()
    edits_after = mgr.get_pending_edits()
    assert len(edits_after) == 0


def test_wiki_pending_edits_reject(wiki_structure):
    mgr = WikiPendingEditsManager(wiki_structure)
    mgr.add_pending_edit("Test Concept", _VALID_DRAFT)

    edits = mgr.get_pending_edits()
    edit_id = edits[0]["id"]

    success = mgr.reject_edit(edit_id)
    assert success is True

    article_path = wiki_structure.get_concept_file_path("Test Concept")
    assert not article_path.exists()

    edits_after = mgr.get_pending_edits()
    assert len(edits_after) == 0


@pytest.mark.asyncio
async def test_approve_nonexistent_edit(wiki_structure, mock_indexer):
    mgr = WikiPendingEditsManager(wiki_structure, indexer=mock_indexer)
    result = await mgr.approve_edit(99999)
    assert result is False


def test_reject_nonexistent_edit(wiki_structure):
    mgr = WikiPendingEditsManager(wiki_structure)
    result = mgr.reject_edit(99999)
    assert result is False


def test_get_stats(wiki_structure):
    mgr = WikiPendingEditsManager(wiki_structure)

    stats = mgr.get_stats()
    assert stats == {"pending": 0, "approved": 0, "rejected": 0}

    mgr.add_pending_edit("A", _VALID_DRAFT)
    mgr.add_pending_edit("B", _VALID_DRAFT)
    mgr.reject_edit(mgr.get_pending_edits()[0]["id"])

    stats = mgr.get_stats()
    assert stats["pending"] == 1
    assert stats["rejected"] == 1


def test_get_edits_created_since_is_status_agnostic_and_ordered(wiki_structure):
    from datetime import UTC, datetime, timedelta

    mgr = WikiPendingEditsManager(wiki_structure)
    reviewed_id = mgr.add_pending_edit("Knowledge/ReviewedByUser", _VALID_DRAFT)
    mgr.add_pending_edit("Methods/StillPending", _VALID_DRAFT)
    mgr.add_pending_edit("Comparisons/StillPending", _VALID_DRAFT)
    mgr.reject_edit(reviewed_id)

    since = (datetime.now(UTC) - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
    edits = mgr.get_edits_created_since(since)
    names = [edit["concept_name"] for edit in edits]

    # Reviewed drafts stay visible: window stats must reflect what the
    # pipeline produced, not what is still pending.
    assert set(names) == {"Knowledge/ReviewedByUser", "Methods/StillPending", "Comparisons/StillPending"}
    assert mgr.get_stats()["pending"] == 2
    assert mgr.get_stats()["rejected"] == 1

    # Limit keeps a subset of the window rows only.
    limited = mgr.get_edits_created_since(since, limit=2)
    assert len(limited) == 2
    assert {edit["concept_name"] for edit in limited} <= set(names)

    # A future cutoff sees nothing.
    future = (datetime.now(UTC) + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    assert mgr.get_edits_created_since(future) == []

    # Offset pages through the same newest-first ordering.
    paged = mgr.get_edits_created_since(since, limit=1, offset=1)
    assert len(paged) == 1
    assert paged[0]["concept_name"] != edits[0]["concept_name"]

    # The created_at window predicate is backed by an index, symmetric with idx_status.
    with mgr._get_conn() as conn:
        index_names = {row["name"] for row in conn.execute("PRAGMA index_list('pending_edits')")}
    assert {"idx_status", "idx_created_at"} <= index_names


def test_get_pending_edits_pages_with_offset(wiki_structure):
    mgr = WikiPendingEditsManager(wiki_structure)
    for i in range(5):
        mgr.add_pending_edit(f"Knowledge/Page {i}", _VALID_DRAFT)

    first_page = mgr.get_pending_edits(limit=3)
    second_page = mgr.get_pending_edits(limit=3, offset=3)
    tail = mgr.get_pending_edits(limit=3, offset=4)

    assert len(first_page) == 3
    assert len(second_page) == 2
    assert len(tail) == 1
    first_names = {edit["concept_name"] for edit in first_page}
    second_names = {edit["concept_name"] for edit in second_page}
    assert first_names.isdisjoint(second_names), "pages must not overlap"
    all_names = first_names | second_names | {edit["concept_name"] for edit in tail}
    assert len(all_names) == 5, "offset pagination must reach every pending draft"


@pytest.mark.asyncio
async def test_approve_with_modified_content(wiki_structure, mock_indexer):
    mgr = WikiPendingEditsManager(wiki_structure, indexer=mock_indexer)
    mgr.add_pending_edit("Edit Concept", _VALID_DRAFT)

    edits = mgr.get_pending_edits()
    edit_id = edits[0]["id"]

    success = await mgr.approve_edit(edit_id, modified_content=_VALID_EDITED)
    assert success is True

    article_path = wiki_structure.get_concept_file_path("Edit Concept")
    metadata, body = parse_frontmatter(article_path.read_text(encoding="utf-8"))
    assert metadata[PUBLISH_STATUS_KEY] == WikiPublishStatus.PUBLISHED.value
    assert "User-edited final version." in body
    mock_indexer.upsert.assert_awaited_once()


@pytest.mark.asyncio
async def test_approve_blocks_stale_pending(wiki_structure, mock_indexer, monkeypatch: pytest.MonkeyPatch) -> None:
    mgr = WikiPendingEditsManager(wiki_structure, indexer=mock_indexer)
    mgr.add_pending_edit("Stale Concept", _VALID_DRAFT)
    edit_id = mgr.get_pending_edits()[0]["id"]

    monkeypatch.setattr(
        "myrm_agent_harness.toolkits.wiki.pipeline.publication.stale_guard.sources_newer_than_article",
        lambda *_args, **_kwargs: True,
    )

    with pytest.raises(StalePendingApprovalError):
        await mgr.approve_edit(edit_id)


_CLAIMS_DRAFT = """---
type: concept
claims:
  - id: claim.pending.item
    text: Pending fact
    status: supported
    confidence: 0.8
    evidence:
      - kind: raw-source
        sourceId: source.pending
        path: notes.md
        lines: ""
        weight: 1.0
        confidence: 0.7
---

## Compiled Truth
Pending body.
"""


@pytest.mark.asyncio
async def test_approve_preserves_nested_claims(wiki_structure, mock_indexer) -> None:
    from myrm_agent_harness.toolkits.wiki.core.claims_contract import parse_claims_from_content

    mgr = WikiPendingEditsManager(wiki_structure, indexer=mock_indexer)
    mgr.add_pending_edit("Claims Concept", _CLAIMS_DRAFT)
    edit_id = mgr.get_pending_edits()[0]["id"]

    assert await mgr.approve_edit(edit_id) is True

    saved = wiki_structure.get_concept_file_path("Claims Concept").read_text(encoding="utf-8")
    claims = parse_claims_from_content(saved)
    assert len(claims) == 1
    assert claims[0].id == "claim.pending.item"


@pytest.mark.asyncio
async def test_approve_preserves_provenance_fields(wiki_structure, mock_indexer) -> None:
    """Approve must publish source_chat/source_message provenance into the concept file."""
    draft = (
        "---\ntype: concept\n"
        "source_chat: chat-provenance-1\nsource_message: msg-provenance-1\n"
        "compound_provenance: chat-compound\n---\n\n"
        "## Compiled Truth\nTraceable content.\n"
    )
    mgr = WikiPendingEditsManager(wiki_structure, indexer=mock_indexer)
    mgr.add_pending_edit("Provenance Concept", draft)
    edit_id = mgr.get_pending_edits()[0]["id"]

    assert await mgr.approve_edit(edit_id) is True

    saved = wiki_structure.get_concept_file_path("Provenance Concept").read_text(encoding="utf-8")
    metadata, _ = parse_frontmatter(saved)
    assert metadata.get("source_chat") == "chat-provenance-1"
    assert metadata.get("source_message") == "msg-provenance-1"
    assert metadata.get("compound_provenance") == "chat-compound"
    assert metadata.get(PUBLISH_STATUS_KEY) == WikiPublishStatus.PUBLISHED.value
