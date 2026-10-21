"""Unit tests for Workflow Replay and Determinism metrics."""

from myrm_agent_harness.eval.assertions import calculate_trajectory_determinism


def test_trajectory_determinism_identical():
    orig = [
        {"tool_name": "read_file", "arguments": {"path": "a.txt"}},
        {"tool_name": "bash", "arguments": {"command": "ls"}},
    ]
    replay = [
        {"tool_name": "read_file", "arguments": {"path": "a.txt"}},
        {"tool_name": "bash", "arguments": {"command": "ls"}},
    ]
    res = calculate_trajectory_determinism(orig, replay)
    assert res.determinism_score == 1.0
    assert res.verdict == "DETERMINISTIC"
    assert len(res.drifted_tools) == 0


def test_trajectory_determinism_drifted():
    orig = [
        {"tool_name": "read_file", "arguments": {"path": "a.txt"}},
        {"tool_name": "bash", "arguments": {"command": "ls"}},
    ]
    replay = [
        {"tool_name": "read_file", "arguments": {"path": "b.txt"}},
        {"tool_name": "search", "arguments": {"query": "ls"}},
    ]
    res = calculate_trajectory_determinism(orig, replay)
    assert res.determinism_score < 0.95
    assert len(res.drifted_tools) > 0


def test_trajectory_determinism_empty():
    res = calculate_trajectory_determinism([], [])
    assert res.determinism_score == 1.0
    assert res.verdict == "DETERMINISTIC"
