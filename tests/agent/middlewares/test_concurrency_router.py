import pytest

from myrm_agent_harness.agent.middlewares.concurrency_router import (
    build_tool_execution_stages,
    should_parallelize_tool_batch,
)


@pytest.fixture(autouse=True)
def mock_safety_metadata(monkeypatch):
    """Mock resolve_safety_metadata to return predictable values for tests."""
    from myrm_agent_harness.agent.security.tool_registry import SafetyMetadata

    def fake_resolve(tool_name: str) -> SafetyMetadata:
        if tool_name == "safe_tool":
            return SafetyMetadata(is_concurrent_safe=True)
        if tool_name in ["file_write_tool", "file_read_tool", "file_patch_tool"]:
            # file_write_tool and file_patch_tool are not concurrent safe inherently
            # (they modify state), but file_read_tool is concurrent safe.
            # However, for the sake of the test, let's strictly mock their actual metadata in our system:
            is_safe = tool_name == "file_read_tool"
            return SafetyMetadata(is_concurrent_safe=is_safe)
        if tool_name == "terminal_tool":
            return SafetyMetadata(is_concurrent_safe=False)
        if tool_name in ["mcp__ue__list_levels", "mcp__jira__list_issues", "mcp__ue__read_actor"]:
            return SafetyMetadata(
                is_read_only=True,
                is_concurrent_safe=False,
                is_destructive=False,
                is_open_world=False,
            )
        if tool_name == "mcp__ue__mutate_actor":
            return SafetyMetadata(
                is_read_only=False,
                is_concurrent_safe=False,
                is_destructive=True,
            )
        return SafetyMetadata(is_concurrent_safe=False)

    monkeypatch.setattr("myrm_agent_harness.agent.middlewares.concurrency_router.resolve_safety_metadata", fake_resolve)

def test_should_parallelize_single_call():
    # Single tool call is never parallelized (it's meaningless)
    assert not should_parallelize_tool_batch([{"name": "safe_tool"}])

def test_should_parallelize_safe_tools():
    # Multiple safe tools should parallelize
    assert should_parallelize_tool_batch([
        {"name": "safe_tool"},
        {"name": "safe_tool"}
    ])

def test_should_parallelize_non_overlapping_writes():
    # Two file_write_tool writing to different paths -> parallel!
    calls = [
        {"name": "file_write_tool", "args": {"path": "src/a.ts"}},
        {"name": "file_write_tool", "args": {"path": "src/b.ts"}}
    ]
    assert should_parallelize_tool_batch(calls)

def test_should_not_parallelize_overlapping_writes():
    # Two file_write_tool writing to same path -> sequential
    calls = [
        {"name": "file_write_tool", "args": {"path": "src/a.ts"}},
        {"name": "file_write_tool", "args": {"path": "src/a.ts"}}
    ]
    assert not should_parallelize_tool_batch(calls)

def test_should_not_parallelize_overlapping_subdirectories():
    # Write to a directory and a file inside it -> sequential
    calls = [
        {"name": "file_write_tool", "args": {"path": "src/"}},
        {"name": "file_write_tool", "args": {"path": "src/a.ts"}}
    ]
    assert not should_parallelize_tool_batch(calls)

def test_should_not_parallelize_unknown_unsafe_tools():
    # A generic unsafe tool (e.g. terminal) mixed in -> sequential
    calls = [
        {"name": "file_write_tool", "args": {"path": "src/a.ts"}},
        {"name": "terminal_tool", "args": {"command": "echo 1"}}
    ]
    assert not should_parallelize_tool_batch(calls)

def test_should_parallelize_mixed_safe_and_non_overlapping_writes():
    # Safe tool + disjoint writes -> parallel!
    calls = [
        {"name": "safe_tool", "args": {}},
        {"name": "file_write_tool", "args": {"path": "src/a.ts"}},
        {"name": "file_write_tool", "args": {"path": "src/b.ts"}}
    ]
    assert should_parallelize_tool_batch(calls)

def test_should_not_parallelize_missing_args():
    # Malformed tool call -> sequential fallback
    calls = [
        {"name": "file_write_tool", "args": {"path": "src/a.ts"}},
        {"name": "file_write_tool"} # missing args
    ]
    assert not should_parallelize_tool_batch(calls)

def test_should_not_parallelize_missing_path():
    # Valid dict args but no path -> sequential fallback
    calls = [
        {"name": "file_write_tool", "args": {"path": "src/a.ts"}},
        {"name": "file_write_tool", "args": {}}
    ]
    assert not should_parallelize_tool_batch(calls)

def test_should_not_parallelize_overlapping_read_and_write():
    # A read tool (concurrent safe) and write tool targeting the same path should not parallelize
    # This prevents dirty reads.
    calls = [
        {"name": "file_read_tool", "args": {"path": "src/a.ts"}},
        {"name": "file_write_tool", "args": {"path": "src/a.ts"}}
    ]
    assert not should_parallelize_tool_batch(calls)


def test_should_parallelize_host_serial_read_only_across_servers():
    # Host-serial demoted read-only MCP tools can run in parallel across distinct servers.
    calls = [
        {"name": "mcp__ue__list_levels", "args": {}},
        {"name": "mcp__jira__list_issues", "args": {}},
    ]
    assert should_parallelize_tool_batch(calls)


def test_should_not_parallelize_host_serial_read_only_same_server():
    # Two host-serial demoted calls targeting the same MCP server must stay serial.
    calls = [
        {"name": "mcp__ue__list_levels", "args": {}},
        {"name": "mcp__ue__read_actor", "args": {}},
    ]
    assert not should_parallelize_tool_batch(calls)


def test_should_not_parallelize_host_serial_destructive_call():
    # Destructive MCP calls are not eligible for host-serial lane parallelization.
    calls = [
        {"name": "mcp__ue__mutate_actor", "args": {"id": "a1"}},
        {"name": "safe_tool", "args": {}},
    ]
    assert not should_parallelize_tool_batch(calls)


def test_build_tool_execution_stages_splits_host_serial_lane_conflicts():
    calls = [
        {"name": "mcp__ue__list_levels", "args": {}},
        {"name": "mcp__jira__list_issues", "args": {}},
        {"name": "mcp__ue__read_actor", "args": {}},
    ]
    assert build_tool_execution_stages(calls) == [[0, 1], [2]]


def test_build_tool_execution_stages_isolates_unsafe_singleton():
    calls = [
        {"name": "safe_tool", "args": {}},
        {"name": "terminal_tool", "args": {"command": "echo 1"}},
        {"name": "safe_tool", "args": {}},
    ]
    assert build_tool_execution_stages(calls) == [[0], [1], [2]]


def test_build_tool_execution_stages_splits_overlapping_path_calls():
    calls = [
        {"name": "file_write_tool", "args": {"path": "src/a.ts"}},
        {"name": "file_write_tool", "args": {"path": "src/a.ts"}},
        {"name": "file_write_tool", "args": {"path": "src/b.ts"}},
    ]
    assert build_tool_execution_stages(calls) == [[0], [1, 2]]
