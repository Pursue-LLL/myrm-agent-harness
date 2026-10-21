"""Tests for QueryNormalizer"""

from __future__ import annotations

from myrm_agent_harness.agent.meta_tools.skills.search.query_normalizer import QueryNormalizer


class TestQueryNormalizer:
    """Test QueryNormalizer functionality"""

    def test_normalize_basic(self) -> None:
        """Test basic normalization"""
        normalizer = QueryNormalizer()
        assert normalizer.normalize("Query") == "query"
        assert normalizer.normalize("  query  ") == "query"

    def test_normalize_case(self) -> None:
        """Test case normalization"""
        normalizer = QueryNormalizer()
        assert normalizer.normalize("DATABASE") == "database"
        assert normalizer.normalize("PostgreSQL") == "postgresql"

    def test_normalize_punctuation(self) -> None:
        """Test punctuation removal"""
        normalizer = QueryNormalizer()
        assert normalizer.normalize("database?") == "database"
        assert normalizer.normalize("api!") == "api"
        assert normalizer.normalize("hello, world") == "hello world"

    def test_normalize_underscores(self) -> None:
        """Test underscore replacement"""
        normalizer = QueryNormalizer()
        assert normalizer.normalize("postgres_query") == "postgres query"
        assert normalizer.normalize("railway_ticket_booking") == "railway ticket booking"

    def test_normalize_whitespace(self) -> None:
        """Test whitespace normalization"""
        normalizer = QueryNormalizer()
        assert normalizer.normalize("  multiple   spaces  ") == "multiple spaces"
        assert normalizer.normalize("tab\ttab") == "tab tab"

    def test_normalize_chinese(self) -> None:
        """Test Chinese character preservation"""
        normalizer = QueryNormalizer()
        assert normalizer.normalize("数据库查询") == "数据库查询"
        assert normalizer.normalize("火车票！") == "火车票"

    def test_normalize_mixed(self) -> None:
        """Test mixed Chinese-English normalization"""
        normalizer = QueryNormalizer()
        assert normalizer.normalize("数据库_DATABASE?") == "数据库 database"

    def test_normalize_empty(self) -> None:
        """Test empty query"""
        normalizer = QueryNormalizer()
        assert normalizer.normalize("") == ""
        assert normalizer.normalize("   ") == ""
