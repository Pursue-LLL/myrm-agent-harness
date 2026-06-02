"""Tests for sandbox_paths compression support."""

from __future__ import annotations

from myrm_agent_harness.runtime.execution_paths import get_compacted_output_path


class TestSandboxPathsCompression:
    """Test sandbox paths with compression support."""

    def test_get_compacted_output_path_uncompressed(self) -> None:
        """Test generating uncompressed output path."""
        path = get_compacted_output_path("chat_abc123", "web_search")

        assert path.startswith("/persistent/.context/chat_abc123/compacted/")
        assert "web_search_" in path
        assert path.endswith(".txt")
        assert ".gz" not in path

    def test_get_compacted_output_path_compressed(self) -> None:
        """Test generating compressed output path."""
        path = get_compacted_output_path("chat_abc123", "web_search", compressed=True)

        assert path.startswith("/persistent/.context/chat_abc123/compacted/")
        assert "web_search_" in path
        assert path.endswith(".txt.gz")

    def test_get_compacted_output_path_explicit_false(self) -> None:
        """Test generating path with explicit compressed=False."""
        path = get_compacted_output_path("chat_abc123", "bash", compressed=False)

        assert path.endswith(".txt")
        assert ".gz" not in path

    def test_path_uniqueness(self) -> None:
        """Test that generated paths are unique."""
        paths = [get_compacted_output_path("chat_abc123", "web_search") for _ in range(10)]

        # All paths should be unique (due to UUID)
        assert len(set(paths)) == 10

    def test_path_sanitization_with_compression(self) -> None:
        """Test that path sanitization works with compression."""
        # Path with special characters
        path = get_compacted_output_path("chat/../evil", "web_search", compressed=True)

        # Should sanitize and still have .txt.gz extension
        assert "/.." not in path
        assert path.endswith(".txt.gz")

    def test_compression_flag_consistency(self) -> None:
        """Test that compression flag is consistent across calls."""
        path1 = get_compacted_output_path("session1", "tool1", compressed=True)
        path2 = get_compacted_output_path("session1", "tool1", compressed=True)

        # Both should have .gz extension
        assert path1.endswith(".txt.gz")
        assert path2.endswith(".txt.gz")

        # But should be different paths (different UUIDs)
        assert path1 != path2
