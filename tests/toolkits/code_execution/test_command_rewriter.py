"""Tests for the command workspace-path rewriter.

Covers the container-convention ``/workspace`` substitution and the guard that
protects an already-resolved real workspace path (e.g. eval graders embedding
``{workspace}`` where the cache layout ends in ``/workspace``) from being
re-expanded into a duplicated path.
"""

from pathlib import Path

from myrm_agent_harness.toolkits.code_execution.executors.common.command_rewriter import (
    CommandRewriter,
)


def _rewrite(command: str, workspace: str | None) -> str:
    rewriter = CommandRewriter()
    if workspace is None:
        return rewriter.rewrite_workspace_paths(command, None)
    return rewriter.rewrite_workspace_paths(command, Path(workspace))


class TestRewriteWorkspacePaths:
    def test_container_convention_replaced(self) -> None:
        assert _rewrite("cd /workspace && python3 main.py", "/tmp/ws") == (
            "cd /tmp/ws && python3 main.py"
        )

    def test_path_arguments_replaced(self) -> None:
        assert (
            _rewrite("cat /workspace/README.md", "/tmp/ws") == "cat /tmp/ws/README.md"
        )

    def test_real_workspace_path_not_duplicated(self) -> None:
        """A real workspace ending in /workspace stays byte-identical."""
        ws = "/data/wb_bench/workspaces/code/t1/workspace"
        command = (
            f"WORKSPACE={ws} LOG_DIR={ws}/.wb_bench/logs python3 {ws}/tests/verifier.py"
        )
        assert _rewrite(command, ws) == command

    def test_mixed_real_and_convention_paths(self) -> None:
        ws = "/data/wb_bench/workspaces/code/t1/workspace"
        command = f"cd /workspace && echo {ws} > out.txt"
        assert _rewrite(command, ws) == f"cd {ws} && echo {ws} > out.txt"

    def test_no_workspace_path_returns_unchanged(self) -> None:
        assert _rewrite("echo hello", "/tmp/ws") == "echo hello"

    def test_none_workspace_returns_unchanged(self) -> None:
        assert _rewrite("echo hello", None) == "echo hello"
