from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.pipeline.pending import WikiPendingEditsManager
from myrm_agent_harness.toolkits.wiki.retrieval.indexer import WikiIndexer


@pytest.fixture
def wiki_structure(tmp_path):
    structure = WikiStructure(tmp_path)
    structure.ensure_structure()
    return structure


@pytest.fixture
def mock_indexer():
    indexer = AsyncMock(spec=WikiIndexer)
    indexer.upsert = AsyncMock()
    return indexer


def test_wiki_pending_edits_add_and_list(wiki_structure):
    mgr = WikiPendingEditsManager(wiki_structure)
    mgr.add_pending_edit("Test Concept", "Proposed content.")

    edits = mgr.get_pending_edits()
    assert len(edits) == 1
    assert edits[0]["concept_name"] == "Test Concept"
    assert edits[0]["proposed_content"] == "Proposed content."
    assert edits[0]["status"] == "pending"


@pytest.mark.asyncio
async def test_wiki_pending_edits_approve(wiki_structure, mock_indexer):
    mgr = WikiPendingEditsManager(wiki_structure, indexer=mock_indexer)
    mgr.add_pending_edit("Test Concept", "Approved content.")

    edits = mgr.get_pending_edits()
    edit_id = edits[0]["id"]

    success = await mgr.approve_edit(edit_id)
    assert success is True

    # Verify file is written
    article_path = wiki_structure.get_concept_file_path("Test Concept")
    assert article_path.exists()
    assert article_path.read_text(encoding="utf-8") == "Approved content."

    # Verify indexer upsert is called
    mock_indexer.upsert.assert_awaited_once_with("Test Concept", "Approved content.")

    # Verify edit status is approved
    edits_after = mgr.get_pending_edits()
    assert len(edits_after) == 0


def test_wiki_pending_edits_reject(wiki_structure):
    mgr = WikiPendingEditsManager(wiki_structure)
    mgr.add_pending_edit("Test Concept", "Rejected content.")

    edits = mgr.get_pending_edits()
    edit_id = edits[0]["id"]

    success = mgr.reject_edit(edit_id)
    assert success is True

    # Verify file is not written
    article_path = wiki_structure.get_concept_file_path("Test Concept")
    assert not article_path.exists()

    # Verify edit status is rejected
    edits_after = mgr.get_pending_edits()
    assert len(edits_after) == 0


@pytest.mark.asyncio
async def test_approve_nonexistent_edit(wiki_structure, mock_indexer):
    """approve_edit returns False when edit_id doesn't exist."""
    mgr = WikiPendingEditsManager(wiki_structure, indexer=mock_indexer)
    result = await mgr.approve_edit(99999)
    assert result is False


def test_reject_nonexistent_edit(wiki_structure):
    """reject_edit returns False when edit_id doesn't exist."""
    mgr = WikiPendingEditsManager(wiki_structure)
    result = mgr.reject_edit(99999)
    assert result is False


def test_get_stats(wiki_structure):
    """get_stats returns correct counts per status."""
    mgr = WikiPendingEditsManager(wiki_structure)

    stats = mgr.get_stats()
    assert stats == {"pending": 0, "approved": 0, "rejected": 0}

    mgr.add_pending_edit("A", "content a")
    mgr.add_pending_edit("B", "content b")
    mgr.reject_edit(mgr.get_pending_edits()[0]["id"])

    stats = mgr.get_stats()
    assert stats["pending"] == 1
    assert stats["rejected"] == 1


@pytest.mark.asyncio
async def test_approve_with_modified_content(wiki_structure, mock_indexer):
    """approve_edit uses modified_content when provided."""
    mgr = WikiPendingEditsManager(wiki_structure, indexer=mock_indexer)
    mgr.add_pending_edit("Edit Concept", "Original draft.")

    edits = mgr.get_pending_edits()
    edit_id = edits[0]["id"]

    success = await mgr.approve_edit(edit_id, modified_content="User-edited final version.")
    assert success is True

    article_path = wiki_structure.get_concept_file_path("Edit Concept")
    assert article_path.read_text(encoding="utf-8") == "User-edited final version."
    mock_indexer.upsert.assert_awaited_once_with("Edit Concept", "User-edited final version.")
