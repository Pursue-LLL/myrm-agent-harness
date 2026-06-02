from myrm_agent_harness.agent.skills.evolution.core.types import EvolutionType
from myrm_agent_harness.agent.skills.evolution.infra.metrics import (
    EvolutionMetrics,
    EvolutionMetricsTracker,
    get_metrics_tracker,
)


def test_metrics_properties_zero():
    m = EvolutionMetrics()
    assert m.success_rate == 0.0
    assert m.fix_success_rate == 0.0
    assert m.derived_success_rate == 0.0
    assert m.captured_success_rate == 0.0

def test_metrics_properties_nonzero():
    m = EvolutionMetrics(
        total_evolutions=10, successful_evolutions=5,
        fix_count=4, fix_success=2,
        derived_count=4, derived_success=2,
        captured_count=2, captured_success=1
    )
    assert m.success_rate == 0.5
    assert m.fix_success_rate == 0.5
    assert m.derived_success_rate == 0.5
    assert m.captured_success_rate == 0.5

def test_tracker_record_evolution():
    tracker = EvolutionMetricsTracker()

    tracker.record_evolution("skill1", EvolutionType.FIX, True)
    tracker.record_evolution("skill1", EvolutionType.DERIVED, False)
    tracker.record_evolution("skill2", EvolutionType.CAPTURED, True)

    metrics = tracker.get_metrics()
    assert metrics.total_evolutions == 3
    assert metrics.successful_evolutions == 2
    assert metrics.failed_evolutions == 1

    assert metrics.fix_count == 1
    assert metrics.fix_success == 1
    assert metrics.derived_count == 1
    assert metrics.derived_success == 0
    assert metrics.captured_count == 1
    assert metrics.captured_success == 1

    report = tracker.get_report()
    assert report["summary"]["total"] == 3
    assert report["summary"]["success"] == 2
    assert report["by_type"]["fix"]["count"] == 1
    assert report["skills_evolved"] == 2

    top = tracker.get_top_skills()
    assert len(top) == 2
    assert top[0][0] == "skill1"  # total 2
    assert top[0][2] == 2

def test_tracker_record_tool_call():
    tracker = EvolutionMetricsTracker()
    tracker.record_tool_call("toolA", 1.5, True)
    tracker.record_tool_call("toolB", 0.5, False)

    metrics = tracker.get_metrics()
    assert metrics.tool_call_count == 2
    assert metrics.tool_call_time == 2.0
    assert metrics.tool_errors == 1

    report = tracker.get_report()
    assert report["tool_usage"]["total_calls"] == 2

def test_tracker_record_summarization():
    tracker = EvolutionMetricsTracker()
    tracker.record_summarization(100, 50, 0.1)

    metrics = tracker.get_metrics()
    assert metrics.summarization_count == 1
    assert metrics.summarization_time == 0.1
    assert metrics.token_saved == 12  # (100 - 50) // 4

    report = tracker.get_report()
    assert report["summarization"]["count"] == 1
    assert report["summarization"]["token_saved"] == 12

def test_tracker_reset():
    tracker = EvolutionMetricsTracker()
    tracker.record_evolution("skill1", EvolutionType.FIX, True)
    tracker.reset()

    metrics = tracker.get_metrics()
    assert metrics.total_evolutions == 0
    assert len(tracker.get_top_skills()) == 0

def test_get_metrics_tracker():
    # Test singleton
    t1 = get_metrics_tracker()
    t2 = get_metrics_tracker()
    assert t1 is t2

def test_get_report_empty():
    tracker = EvolutionMetricsTracker()
    report = tracker.get_report()
    assert report["tool_usage"]["avg_time_per_call"] == "N/A"
    assert report["summarization"]["avg_time"] == "N/A"
