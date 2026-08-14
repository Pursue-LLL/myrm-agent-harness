import pytest

from myrm_agent_harness.agent.skills.evolution.execution.dependency import (
    SkillDependencies,
    SkillDependencyTracker,
    get_dependency_tracker,
    parse_skill_dependencies,
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
    content = """
    @tool_use("github_tool")
    uses: slack_api
    some text mentioning custom_client somewhere
    """
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


def test_parse_skill_dependencies_frontmatter_only():
    content = """---
name: web-scraper
description: Scrape pages
dependencies:
  - http-client
  - html-parser
version: 2
---

Body text without tool references.
"""
    deps = parse_skill_dependencies(content)
    assert deps.skill_deps == ("http-client", "html-parser")
    assert deps.tool_deps == ()


def test_parse_skill_dependencies_body_markers():
    content = """---
name: web-scraper
description: Scrape pages
---

Uses @tool_use("browser_navigate") to visit pages.
Fallback: uses: http_fetch.
"""
    deps = parse_skill_dependencies(content)
    assert deps.skill_deps == ()
    assert set(deps.tool_deps) == {"browser_navigate", "http_fetch"}


def test_parse_skill_dependencies_dedupes_and_orders():
    content = """---
name: s
description: d
dependencies: [b, a, b]
---

@tool_use("http_tool") then @tool_use("http_tool")
"""
    deps = parse_skill_dependencies(content)
    assert deps.skill_deps == ("b", "a")
    assert deps.tool_deps == ("http_tool",)


def test_parse_skill_dependencies_no_frontmatter():
    content = "plain skill with no markers"
    deps = parse_skill_dependencies(content)
    assert deps == SkillDependencies()


def test_parse_skill_dependencies_invalid_yaml_is_safe():
    content = """---
name: s
description: [unclosed
---

@tool_use("x_tool")
"""
    deps = parse_skill_dependencies(content)
    assert deps.skill_deps == ()
    assert "x_tool" in deps.tool_deps
