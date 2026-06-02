"""Tests for TypoCorrector"""

from __future__ import annotations

from myrm_agent_harness.agent.meta_tools.skills.search.typo_corrector import TypoCorrector


class TestTypoCorrector:
    """Test TypoCorrector functionality"""

    def test_correct_database_typos(self) -> None:
        """Test database-related typo corrections"""
        corrector = TypoCorrector()
        assert corrector.correct("databse") == "database"
        assert corrector.correct("databas") == "database"
        assert corrector.correct("postgre") == "postgres"
        assert corrector.correct("postgress") == "postgres"

    def test_correct_tech_terms(self) -> None:
        """Test technical term typo corrections"""
        corrector = TypoCorrector()
        assert corrector.correct("kubernets") == "kubernetes"
        assert corrector.correct("kubernete") == "kubernetes"
        assert corrector.correct("javascirpt") == "javascript"
        assert corrector.correct("pytohn") == "python"
        assert corrector.correct("dock") == "docker"

    def test_correct_auth_typos(self) -> None:
        """Test authentication typo corrections"""
        corrector = TypoCorrector()
        assert "authentication" in corrector.correct("authentification")
        assert "authentication" in corrector.correct("authentcation")
        assert "authentication" in corrector.correct("autentication")

    def test_correct_chinese_pinyin(self) -> None:
        """Test pinyin to Chinese corrections"""
        corrector = TypoCorrector()
        assert corrector.correct("piao") == "票"
        assert corrector.correct("tianqi") == "天气"

    def test_correct_no_typo(self) -> None:
        """Test that correct words are unchanged"""
        corrector = TypoCorrector()
        assert corrector.correct("database") == "database"
        assert corrector.correct("kubernetes") == "kubernetes"
        assert corrector.correct("python") == "python"

    def test_correct_empty(self) -> None:
        """Test empty query"""
        corrector = TypoCorrector()
        assert corrector.correct("") == ""

    def test_correct_multi_word(self) -> None:
        """Test multi-word query with typos"""
        corrector = TypoCorrector()
        assert corrector.correct("databse query") == "database query"
        assert corrector.correct("postgress backup") == "postgres backup"
