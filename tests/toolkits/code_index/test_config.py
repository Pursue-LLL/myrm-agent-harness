"""Tests for CodeIndexConfig defaults and overrides.

Covers:
- Default values for all config fields
- Custom overrides via constructor
- Frozen immutability
- Exclude dirs include all critical build/cache directories
- Binary extensions cover common non-text files
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.code_index.config import CodeIndexConfig


class TestCodeIndexConfigDefaults:
    """Verify all default values are sensible and present."""

    def test_max_file_size_512kb(self) -> None:
        config = CodeIndexConfig()
        assert config.max_file_size_bytes == 512 * 1024

    def test_max_files_50k(self) -> None:
        assert CodeIndexConfig().max_files == 50_000

    def test_batch_size_100(self) -> None:
        assert CodeIndexConfig().batch_size == 100

    def test_max_search_results_20(self) -> None:
        assert CodeIndexConfig().max_search_results == 20

    def test_enable_vector_search_true(self) -> None:
        assert CodeIndexConfig().enable_vector_search is True

    def test_index_db_name(self) -> None:
        assert CodeIndexConfig().index_db_name == "code_index.db"

    def test_collection_name(self) -> None:
        assert CodeIndexConfig().collection_name == "code_chunks"

    def test_exclude_dirs_contains_critical(self) -> None:
        dirs = CodeIndexConfig().exclude_dirs
        for expected in ("node_modules", "__pycache__", ".git", ".venv", ".myrm", "dist", "build"):
            assert expected in dirs, f"{expected} missing from exclude_dirs"

    def test_binary_extensions_contains_critical(self) -> None:
        exts = CodeIndexConfig().binary_extensions
        for expected in (".pyc", ".jpg", ".zip", ".sqlite", ".lock", ".pdf"):
            assert expected in exts, f"{expected} missing from binary_extensions"


class TestCodeIndexConfigOverrides:
    """Custom values override defaults correctly."""

    def test_custom_max_files(self) -> None:
        config = CodeIndexConfig(max_files=100)
        assert config.max_files == 100

    def test_custom_batch_size(self) -> None:
        config = CodeIndexConfig(batch_size=50)
        assert config.batch_size == 50

    def test_disable_vector_search(self) -> None:
        config = CodeIndexConfig(enable_vector_search=False)
        assert config.enable_vector_search is False

    def test_custom_db_name(self) -> None:
        config = CodeIndexConfig(index_db_name="my_index.db")
        assert config.index_db_name == "my_index.db"


class TestCodeIndexConfigImmutability:
    """Config is frozen dataclass — no mutation allowed."""

    def test_frozen(self) -> None:
        config = CodeIndexConfig()
        with pytest.raises(AttributeError):
            config.max_files = 999  # type: ignore[misc]
