import pytest

from myrm_agent_harness.agent.skills.evolution.execution.dependency import (
    SkillDependencyTracker,
    get_dependency_tracker,
)


@pytest.fixture
def tracker():
    return SkillDependencyTracker()

def test_add_dependency(tracker):
    tracker.add_dependency("skillA", "skillB")

    assert tracker.get_dependencies("skillA") == ["skillB"]
    assert tracker.get_dependents("skillB") == ["skillA"]

    # Adding again shouldn't duplicate
    tracker.add_dependency("skillA", "skillB")
    assert len(tracker.get_dependencies("skillA")) == 1

def test_remove_dependency(tracker):
    tracker.add_dependency("skillA", "skillB")
    tracker.add_dependency("skillA", "skillC")

    tracker.remove_dependency("skillA", "skillB")
    assert tracker.get_dependencies("skillA") == ["skillC"]
    assert tracker.get_dependents("skillB") == []

    # Removing non-existent shouldn't crash
    tracker.remove_dependency("skillA", "skillD")

def test_can_evolve_safely(tracker):
    tracker.add_dependency("skillA", "skillB")

    can_evolve, reason = tracker.can_evolve_safely("skillA")
    assert can_evolve is True
    assert "No dependents" in reason

    can_evolve, reason = tracker.can_evolve_safely("skillB")
    assert can_evolve is True
    assert "Warning" in reason
    assert "skillA" in reason

def test_get_evolution_order(tracker):
    # A depends on B, B depends on C
    tracker.add_dependency("skillA", "skillB")
    tracker.add_dependency("skillB", "skillC")

    # We want to evolve them in topological order (dependencies first)
    # The actual algorithm puts independent nodes first.
    # C has 0 dependencies, so C goes first.
    # B has 1 (C), so after C is processed, B's in-degree becomes 0.
    # Wait, the logic is: in_degree counts how many things sid depends on.
    order = tracker.get_evolution_order(["skillA", "skillB", "skillC"])
    assert order == ["skillC", "skillB", "skillA"]

def test_get_evolution_order_cycle(tracker):
    # A -> B -> A
    tracker.add_dependency("skillA", "skillB")
    tracker.add_dependency("skillB", "skillA")

    # The cycle should just append remaining
    order = tracker.get_evolution_order(["skillA", "skillB"])
    assert len(order) == 2
    assert set(order) == {"skillA", "skillB"}

def test_clear(tracker):
    tracker.add_dependency("skillA", "skillB")
    tracker.track_runtime_call("skillA", "toolX")
    tracker.clear()

    assert tracker.get_dependencies("skillA") == []
    assert tracker.get_tool_usage("skillA") == []

def test_auto_track_from_content(tracker):
    content = '''
    @tool_use("github_tool")
    uses: slack_api
    some text mentioning custom_client somewhere
    '''
    tracker.auto_track_from_content("skillA", content)

    tools = tracker.get_tool_usage("skillA")
    assert set(tools) == {"github_tool", "slack_api", "custom_client"}

    assert tracker.find_skills_by_tool("github_tool") == ["skillA"]

def test_track_runtime_call(tracker):
    tracker.track_runtime_call("skillA", "test_tool")

    assert tracker.get_tool_usage("skillA") == ["test_tool"]
    assert tracker.find_skills_by_tool("test_tool") == ["skillA"]
    assert tracker.get_tool_usage_count("test_tool") == 1

def test_get_dependency_tracker():
    # To test singleton
    global _global_tracker

    try:
        t1 = get_dependency_tracker()
        t2 = get_dependency_tracker()
        assert t1 is t2
    finally:
        pass
