"""Tests for checkpoint metadata structure and parsing."""

import pytest

from myrm_agent_harness.toolkits.browser.checkpoint import (
    CheckpointMetadata,
    extract_metadata_from_messages,
    merge_metadata,
)


class TestMetadataExtraction:
    """Test metadata extraction from message history."""

    def test_extract_current_url_from_snapshot(self) -> None:
        """Should extract current_url from snapshot output."""
        messages = [{"content": "[42 refs | ~180 tokens | title: Login | url: example.com/login]"}]

        metadata = extract_metadata_from_messages(messages)

        assert metadata["current_url"] == "example.com/login"

    def test_extract_current_url_from_navigation(self) -> None:
        """Should extract current_url from navigation call."""
        messages = [{"content": 'browser_navigate url="https://example.com/page"'}]

        metadata = extract_metadata_from_messages(messages)

        assert metadata["current_url"] == "https://example.com/page"

    def test_extract_session_domain(self) -> None:
        """Should extract session_domain from session operations."""
        messages = [{"content": 'save_session domain="github.com"'}]

        metadata = extract_metadata_from_messages(messages)

        assert metadata["session_domain"] == "github.com"

    def test_extract_counters(self) -> None:
        """Should count browser operations."""
        messages = [
            {"content": "browser_snapshot_tool"},
            {"content": "browser_interact action=click"},
            {"content": "browser_navigate_tool url=https://example.com"},
            {"content": "[5 refs | ~100 tokens]"},
            {"content": "click button"},
        ]

        metadata = extract_metadata_from_messages(messages)

        assert "task_counters" in metadata
        counters = metadata["task_counters"]
        assert counters["snapshots"] >= 2  # snapshot + refs header
        assert counters["interactions"] >= 2  # interact + click
        assert counters["navigations"] >= 1

    def test_extract_reverse_chronological(self) -> None:
        """Should scan messages in reverse (most recent first)."""
        messages = [
            {"content": "[10 refs | ~50 tokens | url: example.com/old]"},
            {"content": "[10 refs | ~50 tokens | url: example.com/new]"},
        ]

        metadata = extract_metadata_from_messages(messages)

        # Should use most recent URL (last message scanned in reverse)
        assert metadata["current_url"] == "example.com/new"

    def test_extract_empty_messages_raises_error(self) -> None:
        """Should raise ValueError for empty messages."""
        with pytest.raises(ValueError, match="empty message history"):
            extract_metadata_from_messages([])


class TestMetadataMerge:
    """Test metadata merging logic."""

    def test_merge_with_none_base(self) -> None:
        """Should return update when base is None."""
        update: CheckpointMetadata = {"current_url": "example.com"}

        result = merge_metadata(None, update)

        assert result == update

    def test_merge_with_none_update(self) -> None:
        """Should return base when update is None."""
        base: CheckpointMetadata = {"current_url": "example.com"}

        result = merge_metadata(base, None)

        assert result == base

    def test_merge_overwrites_fields(self) -> None:
        """Should overwrite base fields with update fields."""
        base: CheckpointMetadata = {
            "current_url": "old.com",
            "session_domain": "domain.com",
        }
        update: CheckpointMetadata = {
            "current_url": "new.com",
        }

        result = merge_metadata(base, update)

        assert result["current_url"] == "new.com"
        assert result["session_domain"] == "domain.com"

    def test_merge_task_counters_deeply(self) -> None:
        """Should deep merge task_counters."""
        base: CheckpointMetadata = {"task_counters": {"snapshots": 5, "interactions": 3}}
        update: CheckpointMetadata = {"task_counters": {"interactions": 7, "navigations": 2}}

        result = merge_metadata(base, update)

        assert result["task_counters"] == {
            "snapshots": 5,
            "interactions": 7,  # Updated
            "navigations": 2,  # Added
        }
