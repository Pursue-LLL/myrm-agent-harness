"""Tests for the deterministic publication routing gate and apply staging."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.toolkits.wiki.core.frontmatter_contract import (
    FrontmatterValidationError,
)
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.pipeline.apply import (
    WikiApplyOp,
    WikiApplyRequest,
    apply_wiki_mutation,
)
from myrm_agent_harness.toolkits.wiki.pipeline.pending import WikiPendingEditsManager
from myrm_agent_harness.toolkits.wiki.pipeline.publication import (
    ArticlePublishOutcome,
    PublicationDecision,
    PublicationOrigin,
    evaluate_publication_decision,
    route_concept_publication,
)
from myrm_agent_harness.toolkits.wiki.retrieval.indexer import WikiIndexer

_VALID_DRAFT = "---\ntype: concept\n---\n\n## Compiled Truth\nAgent-authored draft.\n"


@pytest.fixture
def wiki_structure(tmp_path: Path) -> WikiStructure:
    structure = WikiStructure(tmp_path / "wiki")
    structure.ensure_structure()
    return structure


@pytest.fixture
def mock_indexer() -> AsyncMock:
    indexer = AsyncMock(spec=WikiIndexer)
    indexer.upsert = AsyncMock()
    indexer.extract_and_upsert_edges = AsyncMock()
    return indexer


def _pending_edit_count(structure: WikiStructure) -> int:
    return len(WikiPendingEditsManager(structure).get_pending_edits())


def test_evaluate_publication_decision_is_fail_closed() -> None:
    """Only known human origins auto-publish; everything else stages."""
    assert evaluate_publication_decision(PublicationOrigin.HUMAN) is PublicationDecision.AUTO_PUBLISH
    assert evaluate_publication_decision("human") is PublicationDecision.AUTO_PUBLISH
    assert evaluate_publication_decision(PublicationOrigin.AGENT) is PublicationDecision.STAGE_PENDING
    assert evaluate_publication_decision("agent") is PublicationDecision.STAGE_PENDING
    # Fail-closed: unknown origins must never auto-publish.
    assert evaluate_publication_decision("unknown-origin") is PublicationDecision.STAGE_PENDING


@pytest.mark.asyncio
async def test_route_agent_origin_stages_pending(wiki_structure: WikiStructure, mock_indexer: AsyncMock) -> None:
    result = await route_concept_publication(
        wiki_structure,
        mock_indexer,
        "Routed Agent Concept",
        _VALID_DRAFT,
        origin=PublicationOrigin.AGENT,
        provenance="agent",
    )

    assert result.decision is PublicationDecision.STAGE_PENDING
    assert result.pending_edit_id is not None
    assert result.publish_outcome is None
    # Fail-closed to the vault: the draft is NOT published.
    assert not wiki_structure.get_concept_file_path("Routed Agent Concept").exists()
    assert _pending_edit_count(wiki_structure) == 1


@pytest.mark.asyncio
async def test_route_human_origin_publishes_directly(wiki_structure: WikiStructure, mock_indexer: AsyncMock) -> None:
    result = await route_concept_publication(
        wiki_structure,
        mock_indexer,
        "Routed Human Concept",
        _VALID_DRAFT,
        origin=PublicationOrigin.HUMAN,
    )

    assert result.decision is PublicationDecision.AUTO_PUBLISH
    assert result.publish_outcome is ArticlePublishOutcome.PUBLISHED
    assert result.pending_edit_id is None
    assert wiki_structure.get_concept_file_path("Routed Human Concept").exists()
    assert _pending_edit_count(wiki_structure) == 0


@pytest.mark.asyncio
async def test_route_unknown_origin_stages_pending(wiki_structure: WikiStructure, mock_indexer: AsyncMock) -> None:
    result = await route_concept_publication(
        wiki_structure,
        mock_indexer,
        "Unknown Origin Concept",
        _VALID_DRAFT,
        origin="unexpected-origin",
    )

    assert result.decision is PublicationDecision.STAGE_PENDING
    assert not wiki_structure.get_concept_file_path("Unknown Origin Concept").exists()


@pytest.mark.asyncio
async def test_route_invalid_frontmatter_fails_fast(wiki_structure: WikiStructure, mock_indexer: AsyncMock) -> None:
    invalid = "---\ntype: nonexistent\n---\n\nbody\n"
    with pytest.raises(FrontmatterValidationError):
        await route_concept_publication(
            wiki_structure,
            mock_indexer,
            "Bad Frontmatter Concept",
            invalid,
            origin=PublicationOrigin.AGENT,
        )

    # Nothing staged, nothing published.
    assert _pending_edit_count(wiki_structure) == 0
    assert not wiki_structure.get_concept_file_path("Bad Frontmatter Concept").exists()


@pytest.mark.asyncio
async def test_apply_agent_create_note_stages_for_review(wiki_structure: WikiStructure, mock_indexer: AsyncMock) -> None:
    result = await apply_wiki_mutation(
        wiki_structure,
        mock_indexer,
        WikiApplyRequest(
            op=WikiApplyOp.CREATE_NOTE,
            concept_name="notes/agent-note",
            body="Agent-authored note body.",
        ),
        caller="agent",
    )

    assert result.success is True
    assert result.staged_for_review is True
    assert result.pending_edit_id is not None
    # The vault file is not written; the draft awaits human review.
    assert not wiki_structure.get_concept_file_path("notes/agent-note").exists()
    edits = WikiPendingEditsManager(wiki_structure).get_pending_edits()
    assert len(edits) == 1
    assert edits[0]["concept_name"] == "notes/agent-note"
    assert "Agent-authored note body." in edits[0]["proposed_content"]


@pytest.mark.asyncio
async def test_apply_chat_metadata_stages_for_review(wiki_structure: WikiStructure, mock_indexer: AsyncMock) -> None:
    path = wiki_structure.get_concept_file_path("chat/metadata-concept")
    path.write_text(_VALID_DRAFT, encoding="utf-8")

    result = await apply_wiki_mutation(
        wiki_structure,
        mock_indexer,
        WikiApplyRequest(
            op=WikiApplyOp.UPDATE_METADATA,
            concept_name="chat/metadata-concept",
            tags=("chat",),
        ),
        caller="chat",
    )

    assert result.staged_for_review is True
    assert result.pending_edit_id is not None
    # The published file is untouched by chat capture.
    assert "chat" not in path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_apply_settings_replace_publishes_directly(wiki_structure: WikiStructure, mock_indexer: AsyncMock) -> None:
    path = wiki_structure.get_concept_file_path("settings/full-document")
    path.write_text(_VALID_DRAFT, encoding="utf-8")

    result = await apply_wiki_mutation(
        wiki_structure,
        mock_indexer,
        WikiApplyRequest(
            op=WikiApplyOp.REPLACE_FULL_DOCUMENT,
            concept_name="settings/full-document",
            content="---\ntype: concept\n---\n\n## Compiled Truth\nHuman-edited final version.\n",
        ),
        caller="settings",
    )

    assert result.staged_for_review is False
    assert result.pending_edit_id is None
    assert "Human-edited final version." in path.read_text(encoding="utf-8")
    assert _pending_edit_count(wiki_structure) == 0
