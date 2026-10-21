"""Tests for QueryParser"""

from __future__ import annotations

from myrm_agent_harness.agent.meta_tools.skills.search.query_parser import QueryParser


class TestQueryParser:
    """Test QueryParser functionality"""

    def test_init_default_weights(self):
        """Test initialization with default weights"""
        parser = QueryParser()
        assert parser.primary_weight == 1.0
        assert parser.secondary_weight == 0.8
        assert parser.tertiary_weight == 0.6

    def test_init_custom_weights(self):
        """Test initialization with custom weights"""
        parser = QueryParser(primary_weight=1.0, secondary_weight=0.7, tertiary_weight=0.5)
        assert parser.primary_weight == 1.0
        assert parser.secondary_weight == 0.7
        assert parser.tertiary_weight == 0.5

    def test_parse_simple_query(self):
        """Test parsing simple query without '/' delimiter"""
        parser = QueryParser()
        result = parser.parse("database query")
        assert result == [("database", 1.0), ("query", 1.0)]

    def test_parse_single_multilingual_group(self):
        """Test parsing single multilingual group"""
        parser = QueryParser()
        result = parser.parse("火车票/railway/train/booking/ticket")
        assert result == [
            ("火车票", 1.0),
            ("railway", 0.8),
            ("train", 0.6),
            ("booking", 0.6),
            ("ticket", 0.6),
        ]

    def test_parse_multiple_multilingual_groups(self):
        """Test parsing multiple multilingual groups"""
        parser = QueryParser()
        result = parser.parse("火车票/railway/ticket 订票/booking")
        assert result == [
            ("火车票", 1.0),
            ("railway", 0.8),
            ("ticket", 0.6),
            ("订票", 1.0),
            ("booking", 0.8),
        ]

    def test_parse_mixed_format(self):
        """Test parsing mixed format (some with '/', some without)"""
        parser = QueryParser()
        result = parser.parse("database/db query search")
        assert result == [
            ("database", 1.0),
            ("db", 0.8),
            ("query", 1.0),
            ("search", 1.0),
        ]

    def test_parse_four_variants(self):
        """Test parsing group with 4+ variants"""
        parser = QueryParser()
        result = parser.parse("火车票/railway/train/booking/ticket")
        # First gets 1.0, second gets 0.8, third+ get 0.6
        assert result == [
            ("火车票", 1.0),
            ("railway", 0.8),
            ("train", 0.6),
            ("booking", 0.6),
            ("ticket", 0.6),
        ]

    def test_parse_empty_query(self):
        """Test parsing empty query"""
        parser = QueryParser()
        assert parser.parse("") == []
        assert parser.parse("   ") == []

    def test_parse_handles_extra_spaces(self):
        """Test parsing handles extra spaces"""
        parser = QueryParser()
        result = parser.parse("  火车票 / railway  ")
        # Extra spaces within "/" group are trimmed
        assert result == [
            ("火车票", 1.0),
            ("railway", 1.0),  # Note: separate token due to space before "/"
        ]

    def test_parse_handles_trailing_slash(self):
        """Test parsing handles trailing slash"""
        parser = QueryParser()
        result = parser.parse("database/db/")
        # Trailing "/" should be filtered out
        assert result == [
            ("database", 1.0),
            ("db", 0.8),
        ]

    def test_format_for_bm25(self):
        """Test formatting for BM25 search"""
        parser = QueryParser()
        result = parser.format_for_bm25("火车票/railway ticket/train booking")
        # Should extract all terms
        assert "火车票" in result
        assert "railway ticket" in result
        assert "train booking" in result

    def test_format_for_bm25_simple(self):
        """Test formatting simple query for BM25"""
        parser = QueryParser()
        result = parser.format_for_bm25("database query")
        assert result == "database query"

    def test_has_multilingual_format_true(self):
        """Test detection of multilingual format"""
        parser = QueryParser()
        assert parser.has_multilingual_format("火车票/railway ticket")
        assert parser.has_multilingual_format("database/db query")

    def test_has_multilingual_format_false(self):
        """Test detection of non-multilingual format"""
        parser = QueryParser()
        assert not parser.has_multilingual_format("database query")
        assert not parser.has_multilingual_format("火车票 订票")

    def test_get_primary_terms(self):
        """Test extracting primary terms"""
        parser = QueryParser()
        result = parser.get_primary_terms("火车票/railway/ticket 订票/booking")
        assert result == ["火车票", "订票"]

    def test_get_primary_terms_simple(self):
        """Test extracting primary terms from simple query"""
        parser = QueryParser()
        result = parser.get_primary_terms("database query search")
        assert result == ["database", "query", "search"]

    def test_get_primary_terms_mixed(self):
        """Test extracting primary terms from mixed format"""
        parser = QueryParser()
        result = parser.get_primary_terms("database/db query search/find")
        assert result == ["database", "query", "search"]


class TestQueryParserIntegration:
    """Integration tests for QueryParser"""

    def test_real_world_query_railway(self):
        """Test real-world railway ticket query"""
        parser = QueryParser()
        query = "火车票/railway/train/booking 卧铺/sleeper/berth 北京/Beijing 上海/Shanghai"
        result = parser.parse(query)

        # Check that all terms are parsed
        assert len(result) > 0
        terms = [t for t, _w in result]
        assert "火车票" in terms
        assert "railway" in terms
        assert "train" in terms
        assert "booking" in terms
        assert "卧铺" in terms
        assert "sleeper" in terms

        # Check primary terms
        primary = parser.get_primary_terms(query)
        assert "火车票" in primary
        assert "卧铺" in primary
        assert "北京" in primary
        assert "上海" in primary

    def test_real_world_query_weather(self):
        """Test real-world weather query"""
        parser = QueryParser()
        query = "天气/weather/forecast 预报/prediction 温度/temperature"
        result = parser.parse(query)

        terms = [t for t, _w in result]
        assert "天气" in terms
        assert "weather" in terms
        assert "forecast" in terms
        assert "预报" in terms
        assert "prediction" in terms
        assert "温度" in terms

    def test_real_world_query_database(self):
        """Test real-world database query"""
        parser = QueryParser()
        query = "数据库/database/db 查询/query/SQL search/搜索"
        result = parser.parse(query)

        # Verify multilingual groups are parsed correctly
        terms = [t for t, _w in result]
        assert "数据库" in terms
        assert "database" in terms
        assert "db" in terms
        assert "查询" in terms
        assert "query" in terms
