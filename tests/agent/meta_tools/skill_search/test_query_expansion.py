"""Tests for Query Expansion Module"""

from __future__ import annotations

from myrm_agent_harness.agent.meta_tools.skills.search.query_expansion import QueryExpander
from myrm_agent_harness.agent.meta_tools.skills.search.typo_corrector import TypoCorrector


class TestQueryExpander:
    """Test QueryExpander functionality"""

    def test_init(self) -> None:
        """Test expander initialization with modular components"""
        expander = QueryExpander()
        assert expander is not None
        assert expander._normalizer is not None
        assert expander._typo_corrector is not None
        assert expander._synonym_expander is not None

    def test_expand_with_synonyms_en(self) -> None:
        """Test English synonym expansion"""
        expander = QueryExpander()
        expanded = expander.expand("database")
        assert "database" in expanded
        assert any("db" in q for q in expanded)

    def test_expand_with_synonyms_zh(self) -> None:
        """Test Chinese synonym expansion"""
        expander = QueryExpander()
        expanded = expander.expand("数据库")
        assert "数据库" in expanded
        assert any("database" in q or "db" in q for q in expanded)

    def test_expand_postgres(self) -> None:
        """Test postgres synonym expansion"""
        expander = QueryExpander()
        expanded = expander.expand("postgres")
        assert "postgres" in expanded
        assert any("postgresql" in q for q in expanded)

    def test_expand_train_ticket(self) -> None:
        """Test train ticket synonym expansion"""
        expander = QueryExpander()
        expanded = expander.expand("火车票")
        assert "火车票" in expanded
        assert any("12306" in q or "train" in q for q in expanded)

    def test_typo_correction(self) -> None:
        """Test typo correction"""
        expander = QueryExpander()
        expanded = expander.expand("databse")
        assert any("database" in q for q in expanded)

    def test_empty_query(self) -> None:
        """Test empty query handling"""
        expander = QueryExpander()
        expanded = expander.expand("")
        assert expanded == [""]

    def test_no_expansion_needed(self) -> None:
        """Test query with no known synonyms (underscores normalized to spaces)"""
        expander = QueryExpander()
        expanded = expander.expand("unknown_term_xyz")
        # Underscores are replaced with spaces during normalization
        assert expanded == ["unknown term xyz"]

    def test_expansion_limit(self) -> None:
        """Test expansion is limited to 5 variations"""
        expander = QueryExpander()
        expanded = expander.expand("api")
        assert len(expanded) <= 5

    def test_preprocess(self) -> None:
        """Test query preprocessing"""
        expander = QueryExpander()
        assert expander.preprocess("  multiple   spaces  ") == "multiple spaces"
        assert expander.preprocess("query") == "query"
        assert expander.preprocess("") == ""


class TestQueryExpansionIntegration:
    """Test query expansion integration with search engine"""

    def test_expansion_improves_recall(self) -> None:
        """Test that expansion improves recall for synonym queries"""
        from myrm_agent_harness.agent.meta_tools.skills.search.engine import SkillSearchEngine
        from myrm_agent_harness.backends.skills.types import SkillMetadata

        skills = [
            SkillMetadata(name="postgresql-admin", description="PostgreSQL database administration and management"),
            SkillMetadata(name="mysql-admin", description="MySQL database administration and management"),
            SkillMetadata(name="db-backup", description="Database backup utility for all db systems"),
        ]

        # Test with "db" query - should match via synonym expansion
        engine_with_expand = SkillSearchEngine(skills, min_relevance_score=0.0, enable_query_expansion=True)
        results = engine_with_expand.search_bm25("db", top_k=5)

        # Should find db-related skills
        assert len(results) > 0
        assert any("db" in r.name.lower() or "database" in r.description.lower() for r in results)

    def test_expansion_handles_typos(self) -> None:
        """Test that typo correction generates valid expansions"""
        expander = QueryExpander()

        # Test typo correction through expansion pipeline
        expanded = expander.expand("databse management")
        # Should include corrected version
        assert any("database management" in q for q in expanded)

        # Test TypoCorrector directly
        typo_corrector = TypoCorrector()
        corrected = typo_corrector.correct("databse")
        assert corrected == "database"

    def test_predefined_typo_corrections(self) -> None:
        """Test predefined typo dictionary corrections"""
        typo_corrector = TypoCorrector()

        # Test predefined corrections
        assert "kubernetes" in typo_corrector.correct("kubernets")
        assert "postgres" in typo_corrector.correct("postgress")
        assert "weather" in typo_corrector.correct("wether")
        assert "message" in typo_corrector.correct("mesage")
        assert "authentication" in typo_corrector.correct("autentication")

        # Test that correct words are not changed
        assert typo_corrector.correct("kubernetes") == "kubernetes"
        assert typo_corrector.correct("postgres") == "postgres"


class TestAdaptiveExpansion:
    """Test adaptive query expansion strategy"""

    def test_single_keyword_gets_expansion(self) -> None:
        """Single-keyword queries should trigger synonym expansion"""
        expander = QueryExpander()

        # Single keyword should get synonym expansion
        expanded = expander.expand("database")
        # Should include synonyms like "db", "数据库", etc.
        assert len(expanded) > 1
        assert "database" in expanded

    def test_multilingual_format_skips_expansion(self) -> None:
        """Multilingual format queries should skip synonym expansion"""
        expander = QueryExpander()

        # Multilingual format should skip synonym expansion
        expanded = expander.expand("火车票/railway/train")
        # Should only include normalized version (no synonyms added)
        # Normalized: removes "/" but doesn't add synonyms
        assert len(expanded) <= 2  # Original + maybe typo-corrected, but no synonyms

    def test_adaptive_strategy_comparison(self) -> None:
        """Compare expansion behavior for different query formats"""
        expander = QueryExpander()

        # Single keyword: should expand
        single_expanded = expander.expand("ticket")
        single_count = len(single_expanded)

        # Multilingual format: should NOT expand with synonyms
        multi_expanded = expander.expand("票/ticket/booking")
        multi_count = len(multi_expanded)

        # Single keyword should have more expansions (synonyms added)
        # Multilingual should be minimal (only normalization)
        assert single_count >= multi_count

    def test_adaptive_logs_decision(self, caplog) -> None:
        """Verify adaptive decision is logged for observability"""
        import logging

        expander = QueryExpander()

        with caplog.at_level(logging.INFO):
            # Test multilingual format
            expander.expand("火车票/railway/train")
            # Should log "Multilingual format detected"
            assert any("Multilingual format detected" in record.message for record in caplog.records)

        caplog.clear()

        with caplog.at_level(logging.INFO):
            # Test single keyword
            expander.expand("database")
            # Should log synonym expansion (not multilingual detection)
            assert not any("Multilingual format detected" in record.message for record in caplog.records)
