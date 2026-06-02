"""BM25 搜索引擎单元测试"""

import pytest

from myrm_agent_harness.agent.meta_tools.skills.search.engine import DEFAULT_BM25_MIN_RELEVANCE_SCORE, SkillSearchEngine
from myrm_agent_harness.backends.skills.types import SkillMetadata


@pytest.fixture
def sample_skills() -> list[SkillMetadata]:
    """创建测试技能列表"""
    return [
        SkillMetadata(
            name="railway_ticket_skill",
            description="火车票查询和预订服务 railway ticket booking service",
            storage_skill_id="railway_ticket_skill",
        ),
        SkillMetadata(
            name="weather_forecast_skill",
            description="天气预报查询 weather forecast query",
            storage_skill_id="weather_forecast_skill",
        ),
        SkillMetadata(
            name="database_query_skill",
            description="数据库查询工具 database query tool SQL",
            storage_skill_id="database_query_skill",
        ),
        SkillMetadata(
            name="12306_skill",
            description="12306铁路售票系统 12306 railway ticket system",
            storage_skill_id="12306_skill",
        ),
    ]


class TestSkillSearchEngine:
    """BM25 搜索引擎测试"""

    def test_init(self, sample_skills: list[SkillMetadata]) -> None:
        """测试引擎初始化"""
        engine = SkillSearchEngine(sample_skills)
        assert len(engine._skills) == 4
        assert engine._min_relevance_score == DEFAULT_BM25_MIN_RELEVANCE_SCORE

    def test_init_with_custom_threshold(self, sample_skills: list[SkillMetadata]) -> None:
        """测试自定义阈值初始化"""
        custom_threshold = 0.3
        engine = SkillSearchEngine(sample_skills, min_relevance_score=custom_threshold)
        assert engine._min_relevance_score == custom_threshold

    def test_search_bm25_chinese(self, sample_skills: list[SkillMetadata]) -> None:
        """测试中文BM25搜索"""
        engine = SkillSearchEngine(sample_skills)
        results = engine.search_bm25("火车票")
        assert len(results) > 0
        assert any("railway" in r.name or "railway" in r.description.lower() for r in results)

    def test_search_bm25_english(self, sample_skills: list[SkillMetadata]) -> None:
        """测试英文BM25搜索"""
        engine = SkillSearchEngine(sample_skills, min_relevance_score=-1.0)
        results = engine.search_bm25("railway ticket")
        assert len(results) > 0
        assert any("railway" in r.name or "railway" in r.description.lower() for r in results)

    def test_search_bm25_multilingual(self, sample_skills: list[SkillMetadata]) -> None:
        """测试多语言格式搜索"""
        engine = SkillSearchEngine(sample_skills)
        results = engine.search_bm25("火车票/railway ticket/train booking")
        assert len(results) > 0

    def test_search_bm25_exact_name(self, sample_skills: list[SkillMetadata]) -> None:
        """测试精确名称匹配"""
        engine = SkillSearchEngine(sample_skills)
        results = engine.search_bm25("12306")
        assert len(results) > 0
        assert any("12306" in r.name for r in results)

    def test_search_bm25_empty_query(self, sample_skills: list[SkillMetadata]) -> None:
        """测试空查询"""
        engine = SkillSearchEngine(sample_skills)
        results = engine.search_bm25("")
        assert len(results) == 0

    def test_search_bm25_special_query_star(self, sample_skills: list[SkillMetadata]) -> None:
        """测试特殊查询 *"""
        engine = SkillSearchEngine(sample_skills)
        results = engine.search_bm25("*")
        assert len(results) == 4

    def test_search_bm25_special_query_all(self, sample_skills: list[SkillMetadata]) -> None:
        """测试特殊查询 all"""
        engine = SkillSearchEngine(sample_skills)
        results = engine.search_bm25("all")
        assert len(results) == 4

    def test_search_bm25_no_match(self, sample_skills: list[SkillMetadata]) -> None:
        """测试无匹配结果"""
        engine = SkillSearchEngine(sample_skills)
        results = engine.search_bm25("nonexistent_keyword_xyz")
        assert len(results) == 0

    def test_search_bm25_top_k(self, sample_skills: list[SkillMetadata]) -> None:
        """测试top_k限制"""
        engine = SkillSearchEngine(sample_skills)
        results = engine.search_bm25("*", top_k=2)
        assert len(results) == 4

        results = engine.search_bm25("railway", top_k=1)
        assert len(results) <= 1

    def test_search_regex_simple(self, sample_skills: list[SkillMetadata]) -> None:
        """测试简单regex搜索"""
        engine = SkillSearchEngine(sample_skills)
        results = engine.search_regex("railway")
        assert len(results) > 0
        assert all("railway" in r.name.lower() or "railway" in r.description.lower() for r in results)

    def test_search_regex_pattern(self, sample_skills: list[SkillMetadata]) -> None:
        """测试regex模式"""
        engine = SkillSearchEngine(sample_skills)
        results = engine.search_regex("railway|weather")
        assert len(results) >= 2

    def test_search_regex_case_insensitive(self, sample_skills: list[SkillMetadata]) -> None:
        """测试regex大小写不敏感"""
        engine = SkillSearchEngine(sample_skills)
        results_lower = engine.search_regex("railway")
        results_upper = engine.search_regex("RAILWAY")
        assert len(results_lower) == len(results_upper)

    def test_search_regex_special_pattern_dot_star(self, sample_skills: list[SkillMetadata]) -> None:
        """测试特殊regex模式 .*"""
        engine = SkillSearchEngine(sample_skills)
        results = engine.search_regex(".*")
        assert len(results) == 4

    def test_search_regex_empty_pattern(self, sample_skills: list[SkillMetadata]) -> None:
        """测试空regex模式"""
        engine = SkillSearchEngine(sample_skills)
        results = engine.search_regex("")
        assert len(results) == 0

    def test_search_regex_invalid_pattern(self, sample_skills: list[SkillMetadata]) -> None:
        """测试无效regex模式"""
        engine = SkillSearchEngine(sample_skills)
        results = engine.search_regex("[invalid")
        assert len(results) == 0

    def test_search_regex_top_k(self, sample_skills: list[SkillMetadata]) -> None:
        """测试regex top_k限制"""
        engine = SkillSearchEngine(sample_skills)
        results = engine.search_regex(".*", top_k=2)
        assert len(results) == 2

    def test_score_ordering(self, sample_skills: list[SkillMetadata]) -> None:
        """测试结果按分数降序排列"""
        engine = SkillSearchEngine(sample_skills)
        results = engine.search_bm25("railway ticket")
        if len(results) > 1:
            for i in range(len(results) - 1):
                assert results[i].score >= results[i + 1].score

    def test_stable_tie_break(self, sample_skills: list[SkillMetadata]) -> None:
        """测试相同分数的技能排序稳定性（按名称字典序）"""
        engine = SkillSearchEngine(sample_skills)

        # 多次运行相同查询，确保结果顺序一致
        results1 = engine.search_bm25("test", top_k=10)
        results2 = engine.search_bm25("test", top_k=10)
        results3 = engine.search_bm25("test", top_k=10)

        # 验证结果一致
        assert len(results1) == len(results2) == len(results3)
        for r1, r2, r3 in zip(results1, results2, results3, strict=False):
            assert r1.name == r2.name == r3.name
            assert abs(r1.score - r2.score) < 1e-6
            assert abs(r2.score - r3.score) < 1e-6

        # 验证相同分数的技能按名称字典序排列
        for i in range(len(results1) - 1):
            if abs(results1[i].score - results1[i + 1].score) < 1e-6:
                # 相同分数，检查名称字典序
                assert results1[i].name < results1[i + 1].name, (
                    f"Same score skills not sorted by name: "
                    f"{results1[i].name} (score={results1[i].score:.6f}) should come before "
                    f"{results1[i + 1].name} (score={results1[i + 1].score:.6f})"
                )
