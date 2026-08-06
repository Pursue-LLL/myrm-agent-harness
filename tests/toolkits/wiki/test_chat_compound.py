from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.toolkits.wiki.core.claims_contract import parse_claims_from_content
from myrm_agent_harness.toolkits.wiki.core.frontmatter_contract import load_frontmatter_metadata
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.pipeline.chat_compound import (
    CHAT_COMPOUND_PROVENANCE,
    ChatCompoundError,
    ChatCompoundRequest,
    ChatCompoundTrustContext,
    build_chat_compound_draft,
    find_pending_edit_id_by_source_message,
    stage_chat_compound,
)
from myrm_agent_harness.toolkits.wiki.pipeline.pending import WikiPendingEditsManager
from myrm_agent_harness.toolkits.wiki.retrieval.indexer import WikiIndexer


@pytest.fixture
def wiki_structure(tmp_path) -> WikiStructure:
    structure = WikiStructure(tmp_path)
    structure.ensure_structure()
    return structure


@pytest.fixture
def mock_indexer() -> WikiIndexer:
    indexer = AsyncMock(spec=WikiIndexer)
    indexer.upsert = AsyncMock()
    indexer.extract_and_upsert_edges = AsyncMock()
    return indexer


def test_build_chat_compound_draft_includes_qa_and_metadata(wiki_structure: WikiStructure) -> None:
    draft = build_chat_compound_draft(
        wiki_structure,
        ChatCompoundRequest(
            concept_name="ChatCompounds/2026-08/test-note",
            user_question="What is Python?",
            assistant_answer="Python is a programming language.",
            source_chat="chat-1",
            source_message="msg-1",
            trust=ChatCompoundTrustContext(
                has_knowledge_sources=True,
                has_verified_snapshot=True,
            ),
        ),
    )
    metadata, body = load_frontmatter_metadata(draft)
    assert metadata["source_chat"] == "chat-1"
    assert metadata["source_message"] == "msg-1"
    assert "# Query" in body
    assert "What is Python?" in body
    assert "# Answer" in body
    claims = parse_claims_from_content(draft)
    assert claims
    assert claims[0].status == "supported"


def test_build_chat_compound_draft_marks_unsupported_without_verified_evidence(
    wiki_structure: WikiStructure,
) -> None:
    draft = build_chat_compound_draft(
        wiki_structure,
        ChatCompoundRequest(
            concept_name="ChatCompounds/2026-08/general",
            user_question="Summarize this topic",
            assistant_answer="Here is a general summary.",
            source_chat="chat-2",
            source_message="msg-2",
            trust=ChatCompoundTrustContext(
                has_knowledge_sources=False,
                has_verified_snapshot=False,
            ),
        ),
    )
    assert "Coverage note" in draft
    claims = parse_claims_from_content(draft)
    assert claims[0].status == "unsupported"


@pytest.mark.asyncio
async def test_stage_chat_compound_dedupes_source_message(
    wiki_structure: WikiStructure,
    mock_indexer: WikiIndexer,
) -> None:
    pending_mgr = WikiPendingEditsManager(wiki_structure, indexer=mock_indexer)
    request = ChatCompoundRequest(
        concept_name="ChatCompounds/2026-08/dedup",
        user_question="Q?",
        assistant_answer="A.",
        source_chat="chat-3",
        source_message="msg-dup",
        trust=ChatCompoundTrustContext(False, False),
    )
    first = await stage_chat_compound(wiki_structure, mock_indexer, pending_mgr, request)
    assert first.pending_edit_id > 0

    with pytest.raises(ChatCompoundError) as exc_info:
        await stage_chat_compound(wiki_structure, mock_indexer, pending_mgr, request)
    assert exc_info.value.code == "already_staged"


def test_find_pending_edit_id_by_source_message(wiki_structure: WikiStructure) -> None:
    pending_mgr = WikiPendingEditsManager(wiki_structure)
    draft = build_chat_compound_draft(
        wiki_structure,
        ChatCompoundRequest(
            concept_name="ChatCompounds/2026-08/find",
            user_question="Q",
            assistant_answer="A",
            source_chat="chat-4",
            source_message="msg-find",
            trust=ChatCompoundTrustContext(False, False),
        ),
    )
    pending_mgr.add_pending_edit("ChatCompounds/2026-08/find", draft, provenance=CHAT_COMPOUND_PROVENANCE)
    found = find_pending_edit_id_by_source_message(pending_mgr, "msg-find")
    assert found is not None
