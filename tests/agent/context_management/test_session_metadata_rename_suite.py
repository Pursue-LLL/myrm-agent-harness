"""Unit tests for Hapi session metadata display rename and precedence arbitration suite."""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.context_management.session_metadata_rename import (
    HapiRenameMetadataNameSuite,
    RenameSource,
    SessionRenameReceipt,
    SessionTitleResolution,
    TitlePrecedenceLevel,
)


def test_explicit_rename_updates_metadata_name_and_precedence_arbitration() -> None:
    """Test explicit rename mutates metadata.name and wins over all lower-tier title sources."""
    suite = HapiRenameMetadataNameSuite()
    session_id = "sess_rename_001"

    # Register session with mixed legacy titles
    suite.register_session(
        session_id=session_id,
        initial_metadata={"title": "Old Legacy Title"},
        toplevel_name="Container Session 001",
    )

    # 1. Before rename, metadata.title wins over toplevel_name
    pre_res: SessionTitleResolution = suite.resolve_display_title(
        session_id=session_id,
        fallback_summary="Auto generated summary from turn 1",
    )
    assert pre_res.effective_title == "Old Legacy Title"
    assert pre_res.precedence_level == TitlePrecedenceLevel.METADATA_TITLE

    # 2. Explicit rename writes metadata.name
    receipt: SessionRenameReceipt = suite.rename_session(
        session_id=session_id,
        new_title="  Refactor Payment Gateway API  ",
        source=RenameSource.USER_EXPLICIT,
    )
    assert receipt.success is True
    assert receipt.changed is True
    assert receipt.normalized_name == "Refactor Payment Gateway API"
    assert receipt.source == RenameSource.USER_EXPLICIT

    # 3. Authoritative check: metadata.name now has absolute highest precedence
    post_res: SessionTitleResolution = suite.resolve_display_title(
        session_id=session_id,
        fallback_summary="Auto generated summary from turn 1",
    )
    assert post_res.effective_title == "Refactor Payment Gateway API"
    assert post_res.precedence_level == TitlePrecedenceLevel.METADATA_NAME
    assert post_res.is_explicit_rename is True
    assert post_res.raw_source_field == "metadata.name"


def test_title_normalization_and_blank_rejection() -> None:
    """Test whitespace collapsing, max-length bounding, and rejection of blank titles."""
    suite = HapiRenameMetadataNameSuite()
    session_id = "sess_rename_002"
    suite.register_session(session_id=session_id)

    # 1. Whitespace normalization test
    dirty_title = "   Analyze\n\n\tmemory   leak    in  Worker  "
    norm = suite.normalize_title(dirty_title)
    assert norm == "Analyze memory leak in Worker"

    # 2. Reject pure whitespace
    blank_receipt: SessionRenameReceipt = suite.rename_session(
        session_id=session_id,
        new_title="    \t  \n  ",
    )
    assert blank_receipt.success is False
    assert blank_receipt.changed is False
    assert "rejected" in blank_receipt.message

    # Reject None
    none_receipt: SessionRenameReceipt = suite.rename_session(
        session_id=session_id,
        new_title=None,
    )
    assert none_receipt.success is False
    assert none_receipt.changed is False

    # 3. Max length truncation test
    super_long = "A" * 300
    norm_long = suite.normalize_title(super_long, max_length=20)
    assert norm_long == "A" * 20
    assert len(norm_long) == 20


def test_idempotent_rename_no_op_and_subagent_collab_guard() -> None:
    """Test idempotent renaming skips redundant mutations and guards against subagent hijacking."""
    suite = HapiRenameMetadataNameSuite()
    session_id = "sess_rename_003"
    suite.register_session(session_id=session_id)

    # First rename
    rec_1 = suite.rename_session(session_id=session_id, new_title="Audit Security Rules")
    assert rec_1.success is True
    assert rec_1.changed is True

    # Repeated identical rename is idempotent no-op
    rec_2 = suite.rename_session(session_id=session_id, new_title="Audit Security Rules")
    assert rec_2.success is True
    assert rec_2.changed is False
    assert "already identical" in rec_2.message

    # Subagent collab guard test: child subagent attempting to rename parent session
    collab_blocked = suite.rename_session(
        session_id=session_id,
        new_title="Subagent Hijacked Title",
        source=RenameSource.AGENT_TOOL,
        allow_subagent_rename=False,
        is_subagent=True,
    )
    assert collab_blocked.success is False
    assert collab_blocked.changed is False
    assert "Subagent renaming rejected" in collab_blocked.message

    # Verify original title untouched
    current_title = suite.resolve_display_title(session_id=session_id)
    assert current_title.effective_title == "Audit Security Rules"


def test_smooth_fallback_chain_when_metadata_name_absent() -> None:
    """Test deterministic multi-tier fallback ladder when metadata.name is not set."""
    suite = HapiRenameMetadataNameSuite()

    # 1. Fallback to metadata.title
    r1 = suite.resolve_metadata_direct(
        metadata={"title": "Auxiliary Title"},
        toplevel_name="Container Name",
        fallback_summary="Generated Summary",
    )
    assert r1.effective_title == "Auxiliary Title"
    assert r1.precedence_level == TitlePrecedenceLevel.METADATA_TITLE

    # 2. Fallback to toplevel_name
    r2 = suite.resolve_metadata_direct(
        metadata={},
        toplevel_name="Container Name",
        fallback_summary="Generated Summary",
    )
    assert r2.effective_title == "Container Name"
    assert r2.precedence_level == TitlePrecedenceLevel.TOPLEVEL_NAME

    # 3. Fallback to generated summary
    r3 = suite.resolve_metadata_direct(
        metadata={},
        toplevel_name=None,
        fallback_summary="Generated Summary",
    )
    assert r3.effective_title == "Generated Summary"
    assert r3.precedence_level == TitlePrecedenceLevel.FALLBACK_SUMMARY

    # 4. Fallback to default
    r4 = suite.resolve_metadata_direct(
        metadata={},
        toplevel_name=None,
        fallback_summary=None,
        default_fallback="Safe Default Chat",
    )
    assert r4.effective_title == "Safe Default Chat"
    assert r4.precedence_level == TitlePrecedenceLevel.DEFAULT_FALLBACK
