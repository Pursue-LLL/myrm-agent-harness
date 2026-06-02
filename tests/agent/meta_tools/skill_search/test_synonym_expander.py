"""Tests for SynonymExpander"""

from __future__ import annotations

from myrm_agent_harness.agent.meta_tools.skills.search.synonym_expander import SynonymExpander


class TestSynonymExpander:
    """Test SynonymExpander functionality"""

    def test_expand_english_synonyms(self) -> None:
        """Test English synonym expansion"""
        expander = SynonymExpander()
        expanded = expander.expand("database")
        assert "database" in expanded
        assert any("db" in q for q in expanded)

    def test_expand_chinese_synonyms(self) -> None:
        """Test Chinese synonym expansion"""
        expander = SynonymExpander()
        expanded = expander.expand("数据库")
        assert "数据库" in expanded
        assert any("database" in q or "db" in q for q in expanded)

    def test_expand_multilingual(self) -> None:
        """Test multilingual synonym expansion"""
        expander = SynonymExpander()

        # Chinese to English
        expanded_zh = expander.expand("火车票")
        assert any("railway" in q or "train" in q for q in expanded_zh)

        # English conceptual
        expanded_en = expander.expand("booking")
        assert any("reservation" in q or "ticket" in q for q in expanded_en)

    def test_expand_technical_terms(self) -> None:
        """Test technical term expansion"""
        expander = SynonymExpander()

        expanded = expander.expand("k8s")
        assert any("kubernetes" in q for q in expanded)

        expanded = expander.expand("postgres")
        assert any("postgresql" in q for q in expanded)

    def test_expand_no_match(self) -> None:
        """Test query with no known synonyms"""
        expander = SynonymExpander()
        expanded = expander.expand("unknown term")
        assert expanded == ["unknown term"]

    def test_expand_empty(self) -> None:
        """Test empty query"""
        expander = SynonymExpander()
        expanded = expander.expand("")
        assert expanded == [""]

    def test_expand_limit(self) -> None:
        """Test expansion is limited to 5 variations"""
        expander = SynonymExpander()
        # "api" has multiple synonyms (api, rest, endpoint)
        expanded = expander.expand("api")
        assert len(expanded) <= 5

    def test_external_config_loading(self) -> None:
        """Test that external config can be loaded"""
        from pathlib import Path

        config_path = (
            Path(__file__).parent.parent.parent.parent
            / "src"
            / "myrm_agent_harness"
            / "agent"
            / "meta_tools"
            / "skills"
            / "search"
            / "config"
            / "synonyms.yaml"
        )

        if config_path.exists():
            expander = SynonymExpander(config_path=config_path)
            # Should have loaded from external config
            expanded = expander.expand("数据库")
            assert "数据库" in expanded
            assert any("database" in q or "db" in q for q in expanded)
