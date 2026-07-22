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
        if tool_name in ["file_write_tool", "file_read_tool", "file_edit_tool", "file_patch_tool"]:
            if tool_name == "file_read_tool":
                return SafetyMetadata(is_read_only=True, is_concurrent_safe=True, is_idempotent=True)
            return SafetyMetadata(is_concurrent_safe=False)
        if tool_name in ["grep_tool", "glob_tool"]:
            return SafetyMetadata(is_read_only=True, is_concurrent_safe=True, is_idempotent=True)
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


def test_should_not_parallelize_read_paths_list_with_overlapping_write():
    calls = [
        {"name": "file_read_tool", "args": {"paths": ["src/a.ts", "src/b.ts"]}},
        {"name": "file_write_tool", "args": {"path": "src/a.ts"}},
    ]
    assert not should_parallelize_tool_batch(calls)


def test_should_parallelize_read_paths_list_without_overlapping_write():
    calls = [
        {"name": "file_read_tool", "args": {"paths": ["src/a.ts", "tests/b.ts"]}},
        {"name": "file_write_tool", "args": {"path": "docs/c.md"}},
    ]
    assert should_parallelize_tool_batch(calls)


def test_should_not_parallelize_grep_and_overlapping_write():
    calls = [
        {"name": "grep_tool", "args": {"pattern": "TODO", "path": "src/a.ts"}},
        {"name": "file_write_tool", "args": {"path": "src/a.ts"}},
    ]
    assert not should_parallelize_tool_batch(calls)


def test_should_not_parallelize_glob_and_overlapping_write():
    calls = [
        {"name": "glob_tool", "args": {"pattern": "src/**/*.ts"}},
        {"name": "file_write_tool", "args": {"path": "src/a.ts"}},
    ]
    assert not should_parallelize_tool_batch(calls)


def test_should_not_parallelize_file_id_alias_with_real_path(monkeypatch):
    def fake_resolve(path: str) -> str:
        if path == "@file_001":
            return "/tmp/workspace/src/a.ts"
        return path

    monkeypatch.setattr(
        "myrm_agent_harness.agent.middlewares.concurrency_router._resolve_parallel_scope_path",
        fake_resolve,
    )
    calls = [
        {"name": "file_write_tool", "args": {"path": "@file_001"}},
        {"name": "file_write_tool", "args": {"path": "/tmp/workspace/src/a.ts"}},
    ]
    assert not should_parallelize_tool_batch(calls)


def test_should_not_parallelize_symlink_alias_with_real_path(tmp_path):
    file_path = tmp_path / "real.ts"
    alias_path = tmp_path / "alias.ts"
    file_path.write_text("console.log('ok')", encoding="utf-8")
    try:
        alias_path.symlink_to(file_path)
    except (NotImplementedError, OSError):
        pytest.skip("Symlink not supported on this platform")

    calls = [
        {"name": "file_write_tool", "args": {"path": str(file_path)}},
        {"name": "file_write_tool", "args": {"path": str(alias_path)}},
    ]
    assert not should_parallelize_tool_batch(calls)


def test_should_parallelize_overlapping_reads():
    # Two read calls targeting the same path are now allowed to overlap.
    calls = [
        {"name": "file_read_tool", "args": {"path": "src/a.ts"}},
        {"name": "file_read_tool", "args": {"path": "src/a.ts"}},
    ]
    assert should_parallelize_tool_batch(calls)


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


def test_build_tool_execution_stages_allows_overlapping_reads():
    calls = [
        {"name": "file_read_tool", "args": {"path": "src/a.ts"}},
        {"name": "file_read_tool", "args": {"path": "src/a.ts"}},
        {"name": "file_write_tool", "args": {"path": "src/a.ts"}},
    ]
    assert build_tool_execution_stages(calls) == [[0, 1], [2]]
