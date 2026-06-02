from myrm_agent_harness.agent.skills.evolution.core.types import (
    EvolutionType,
    ExecutionAnalysis,
    SkillLineage,
    SkillMetrics,
    SkillRecord,
)
from myrm_agent_harness.agent.skills.evolution.pipeline.analyzer import (
    SkillExecutionAnalyzer,
    analyze_skill_for_evolution,
)


def create_mock_skill(usage_count=0, success_rate=1.0, consecutive_failures=0):
    success_count = int(usage_count * success_rate)
    metrics = SkillMetrics(
        total_selections=usage_count,
        applied_count=usage_count,
        completed_count=usage_count,
        success_count=success_count,
        consecutive_failures=consecutive_failures
    )
    return SkillRecord(
        skill_id="test_skill",
        name="test_skill",
        description="test",
        content="pass",
        path="test.py",
        lineage=SkillLineage(evolution_type=EvolutionType.DERIVED),
        metrics=metrics
    )

def test_analyzer_insufficient_data():
    analyzer = SkillExecutionAnalyzer(usage_min=3)
    skill = create_mock_skill(usage_count=2)
    rec = analyzer.analyze_skill(skill)
    assert rec.should_fix is False
    assert rec.confidence == 0.0
    assert "Insufficient usage data" in rec.reasons[0]

def test_analyzer_should_fix_consecutive_failures():
    analyzer = SkillExecutionAnalyzer(usage_min=3)
    skill = create_mock_skill(usage_count=5, success_rate=0.4, consecutive_failures=3)
    rec = analyzer.analyze_skill(skill)
    assert rec.should_fix is True
    assert rec.confidence == 0.9
    assert any("consecutive failures" in r for r in rec.reasons)

def test_analyzer_should_fix_low_success_rate():
    analyzer = SkillExecutionAnalyzer(fix_threshold=0.5, usage_min=3)
    skill = create_mock_skill(usage_count=5, success_rate=0.4, consecutive_failures=1)
    rec = analyzer.analyze_skill(skill)
    assert rec.should_fix is True
    assert rec.confidence == 0.9
    assert any("Low success rate" in r for r in rec.reasons)

def test_analyzer_should_derive():
    analyzer = SkillExecutionAnalyzer(usage_min=3)
    skill = create_mock_skill(usage_count=15, success_rate=0.8, consecutive_failures=0)
    rec = analyzer.analyze_skill(skill)
    assert rec.should_derive is True
    assert rec.confidence == 0.6
    assert any("stable and popular" in r for r in rec.reasons)

def test_analyze_execution_history():
    analyzer = SkillExecutionAnalyzer()
    skill = create_mock_skill()
    analysis = ExecutionAnalysis(
        task_id="task1",
        skill_id="test_skill",
        success=False,
        error_message="Connection timeout occurred",
        root_cause="Network issue",
        suggested_fix="Increase timeout"
    )
    summary = analyzer.analyze_execution_history(skill, analysis)
    assert summary.get("error_type") == "timeout"
    assert summary.get("has_root_cause") is True
    assert summary.get("has_suggested_fix") is True

def test_classify_error():
    analyzer = SkillExecutionAnalyzer()
    assert analyzer._classify_error("Permission denied 403") == "permission"
    assert analyzer._classify_error("File not found 404") == "not_found"
    assert analyzer._classify_error("SyntaxError: invalid syntax") == "syntax"
    assert analyzer._classify_error("TypeError: NoneType") == "type_error"
    assert analyzer._classify_error("Some weird bug") == "unknown"

def test_estimate_relevance():
    analyzer = SkillExecutionAnalyzer()
    assert analyzer._estimate_relevance([]) == 0.0
    assert analyzer._estimate_relevance(["ctx1", "ctx2"]) == 0.4
    assert analyzer._estimate_relevance(["1", "2", "3", "4", "5", "6"]) == 1.0

def test_should_evolve_now():
    analyzer = SkillExecutionAnalyzer(fix_threshold=0.5)

    skill_critical = create_mock_skill(consecutive_failures=3)
    evolve, reason = analyzer.should_evolve_now(skill_critical)
    assert evolve is True
    assert "Critical failure" in reason

    skill_low_rate = create_mock_skill(usage_count=5, success_rate=0.4)
    evolve, reason = analyzer.should_evolve_now(skill_low_rate)
    assert evolve is True
    assert "Success rate below threshold" in reason

    skill_ok = create_mock_skill(usage_count=5, success_rate=0.8)
    evolve, reason = analyzer.should_evolve_now(skill_ok)
    assert evolve is False
    assert "performing adequately" in reason

def test_analyze_skill_for_evolution_convenience():
    skill = create_mock_skill(usage_count=1)
    rec = analyze_skill_for_evolution(skill)
    assert rec.should_fix is False
