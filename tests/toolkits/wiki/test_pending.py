from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.agent.meta_tools.file_ops.utils.markdown_frontmatter import parse_frontmatter
from myrm_agent_harness.toolkits.wiki.core.frontmatter_contract import PUBLISH_STATUS_KEY, WikiPublishStatus
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.pipeline.pending import WikiPendingEditsManager
from myrm_agent_harness.toolkits.wiki.pipeline.publication import StalePendingApprovalError
from myrm_agent_harness.toolkits.wiki.retrieval.indexer import WikiIndexer

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
