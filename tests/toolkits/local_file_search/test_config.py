"""Unit tests for local_file_search.config."""

from myrm_agent_harness.toolkits.local_file_search.config import (
    DEFAULT_EXCLUDE_PATTERNS,
    MAX_FILE_SIZE_BYTES,
    SUPPORTED_EXTENSIONS,
    VECTOR_COLLECTION_NAME,
    LocalFileSearchConfig,
)
from myrm_agent_harness.toolkits.local_file_search.models import IndexedDirectory


class TestConstants:
    def test_exclude_patterns_are_frozenset(self):
        assert isinstance(DEFAULT_EXCLUDE_PATTERNS, frozenset)
        assert ".git" in DEFAULT_EXCLUDE_PATTERNS
        assert "node_modules" in DEFAULT_EXCLUDE_PATTERNS
        assert "__pycache__" in DEFAULT_EXCLUDE_PATTERNS

    def test_supported_extensions(self):
        assert isinstance(SUPPORTED_EXTENSIONS, frozenset)
        assert ".pdf" in SUPPORTED_EXTENSIONS
        assert ".md" in SUPPORTED_EXTENSIONS
        assert ".py" in SUPPORTED_EXTENSIONS
        assert ".docx" in SUPPORTED_EXTENSIONS
        assert ".txt" in SUPPORTED_EXTENSIONS

    def test_collection_name(self):
        assert VECTOR_COLLECTION_NAME == "local_file_search"

    def test_max_file_size(self):
        assert MAX_FILE_SIZE_BYTES == 50 * 1024 * 1024


class TestLocalFileSearchConfig:
    def test_defaults(self):
        cfg = LocalFileSearchConfig()
        assert cfg.directories == []
        assert cfg.max_file_size_bytes == MAX_FILE_SIZE_BYTES
        assert cfg.chunk_overlap_tokens == 50
        assert len(cfg.exclude_patterns) > 0

    def test_get_enabled_directories(self):
        dirs = [
            IndexedDirectory(path="/a", enabled=True),
            IndexedDirectory(path="/b", enabled=False),
            IndexedDirectory(path="/c", enabled=True),
        ]
        cfg = LocalFileSearchConfig(directories=dirs)
        enabled = cfg.get_enabled_directories()
        assert len(enabled) == 2
        assert all(d.enabled for d in enabled)

    def test_get_enabled_directories_empty(self):
        cfg = LocalFileSearchConfig()
        assert cfg.get_enabled_directories() == []

    def test_get_exclude_set(self):
        cfg = LocalFileSearchConfig(exclude_patterns=[".git", "node_modules"])
        exclude_set = cfg.get_exclude_set()
        assert isinstance(exclude_set, frozenset)
        assert ".git" in exclude_set
        assert "node_modules" in exclude_set

    def test_json_roundtrip(self):
        dirs = [IndexedDirectory(path="/docs")]
        cfg = LocalFileSearchConfig(directories=dirs)
        data = cfg.model_dump(mode="json")
        restored = LocalFileSearchConfig.model_validate(data)
        assert len(restored.directories) == 1
        assert restored.directories[0].path == "/docs"
