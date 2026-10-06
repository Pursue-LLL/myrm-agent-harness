"""Tests for File-Path SHA-256 Stable Document Session Binding Hub."""

from __future__ import annotations

import pytest

from myrm_agent_harness.runtime.context.path_stable_doc_session import (
    DocChunkCacheEntry,
    PathStableDocSessionHub,
)


def test_deterministic_session_derivation_and_canonicalization(tmp_path):
    hub = PathStableDocSessionHub()
    base_dir = str(tmp_path)
    file_name = "quarterly_financial_report.docx"
    doc_file = tmp_path / file_name
    doc_file.write_text("sample content")

    rel_path_1 = f"./{file_name}"
    rel_path_2 = f"subdir/../{file_name}"
    abs_path = str(doc_file)

    sid_1 = hub.derive_session_id(rel_path_1, base_dir=base_dir)
    sid_2 = hub.derive_session_id(rel_path_2, base_dir=base_dir)
    sid_3 = hub.derive_session_id(abs_path)

    # All representations must resolve to the identical deterministic session id
    assert sid_1 == sid_2 == sid_3
    assert sid_1.startswith("doc-sess-quarterly_financial_repo-")
    assert len(sid_1.split("-")[-1]) == 16


def test_get_or_create_binding_and_access_timestamp(tmp_path):
    hub = PathStableDocSessionHub()
    doc_path = str(tmp_path / "spec.pdf")

    # 1. First creation
    binding1 = hub.get_or_create_binding(doc_path)
    assert binding1.doc_basename == "spec.pdf"
    assert binding1.created_at > 0
    assert binding1.last_accessed_at >= binding1.created_at

    # 2. Second access updates last_accessed_at while preserving created_at
    binding2 = hub.get_or_create_binding(doc_path)
    assert binding2.session_id == binding1.session_id
    assert binding2.created_at == binding1.created_at
    assert binding2.last_accessed_at >= binding1.last_accessed_at


def test_diff_proposals_lifecycle_and_status(tmp_path):
    hub = PathStableDocSessionHub()
    doc_path = str(tmp_path / "architecture_rfc.docx")
    binding = hub.get_or_create_binding(doc_path)
    session_id = binding.session_id

    # Turn 1 proposal
    p1 = hub.record_diff_proposal(
        session_id=session_id,
        turn_index=1,
        target_section="Section 2.1 Storage",
        summary="Add copy-on-write state branching specification",
    )
    assert p1.is_applied is False
    assert p1.is_rejected is False

    # Turn 2 proposal
    p2 = hub.record_diff_proposal(
        session_id=session_id,
        turn_index=2,
        target_section="Section 3.4 API Gateway",
        summary="Deprecate synchronous blocking RPC",
    )

    # Apply turn 1 and reject turn 2
    hub.mark_proposal_status(session_id=session_id, proposal_id=p1.proposal_id, applied=True)
    hub.mark_proposal_status(session_id=session_id, proposal_id=p2.proposal_id, applied=False)

    ctx = hub.generate_continuity_context(session_id)
    assert ctx.total_proposals == 2
    assert ctx.applied_proposals == 1
    assert p1.proposal_id in ctx.active_proposal_ids
    assert p2.proposal_id not in ctx.active_proposal_ids  # Rejected proposal excluded from active


def test_chunk_cache_and_retrieval(tmp_path):
    hub = PathStableDocSessionHub()
    doc_path = str(tmp_path / "handbook.docx")
    binding = hub.get_or_create_binding(doc_path)
    session_id = binding.session_id

    chunks = [
        DocChunkCacheEntry(
            chunk_id="chunk-ch1",
            section_title="Chapter 1: Onboarding",
            content_snippet="Welcome to the organization...",
            token_estimate=120,
            checksum="hash-ch1",
        ),
        DocChunkCacheEntry(
            chunk_id="chunk-ch2",
            section_title="Chapter 2: Security",
            content_snippet="All credentials must be stored securely...",
            token_estimate=180,
            checksum="hash-ch2",
        ),
    ]

    hub.cache_chunks(session_id, chunks)
    cached = hub.get_cached_chunks(session_id)
    assert len(cached) == 2
    titles = {c.section_title for c in cached}
    assert "Chapter 1: Onboarding" in titles
    assert "Chapter 2: Security" in titles


def test_continuity_context_synthesis_xml(tmp_path):
    hub = PathStableDocSessionHub()
    doc_path = str(tmp_path / "rfc_v2.docx")
    binding = hub.get_or_create_binding(doc_path)
    session_id = binding.session_id

    hub.record_diff_proposal(
        session_id=session_id,
        turn_index=1,
        target_section="Executive Summary",
        summary="Revise Q3 projections",
    )
    hub.cache_chunks(
        session_id,
        [
            DocChunkCacheEntry(
                chunk_id="ch-sum",
                section_title="Exec Summary",
                content_snippet="Forecast details...",
                token_estimate=95,
                checksum="chk-1",
            )
        ],
    )

    ctx = hub.generate_continuity_context(session_id)
    assert f'<document_session_continuity session_id="{session_id}"' in ctx.context_summary_xml
    assert 'summary total_proposals="1" applied="0" cached_chunks="1"' in ctx.context_summary_xml
    assert "<diff_proposals_history>" in ctx.context_summary_xml
    assert "Revise Q3 projections" in ctx.context_summary_xml
    assert "<cached_document_sections>" in ctx.context_summary_xml
    assert 'section id="ch-sum" title="Exec Summary"' in ctx.context_summary_xml


def test_multi_doc_isolation_and_error_handling(tmp_path):
    hub = PathStableDocSessionHub()
    doc_a = str(tmp_path / "doc_a.docx")
    doc_b = str(tmp_path / "doc_b.xlsx")

    binding_a = hub.get_or_create_binding(doc_a)
    binding_b = hub.get_or_create_binding(doc_b)

    assert binding_a.session_id != binding_b.session_id
    assert hub.check_multi_doc_isolation(binding_a.session_id, binding_b.session_id) is True

    # Error cases
    with pytest.raises(KeyError, match="Document session 'ghost-sess' not found"):
        hub.record_diff_proposal(
            session_id="ghost-sess",
            turn_index=1,
            target_section="Section",
            summary="test",
        )

    with pytest.raises(KeyError, match="Proposal 'ghost-prop' not found"):
        hub.mark_proposal_status(
            session_id=binding_a.session_id,
            proposal_id="ghost-prop",
            applied=True,
        )
