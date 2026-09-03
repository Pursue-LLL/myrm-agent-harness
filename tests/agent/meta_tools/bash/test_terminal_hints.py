"""Unit tests for terminal output-pattern failure hints and masked-success detection."""

from __future__ import annotations

from myrm_agent_harness.agent.meta_tools.bash._tool.formatting import format_result
from myrm_agent_harness.agent.meta_tools.bash._tool.terminal_hints import (
    annotate_failure,
    annotate_masked_success,
)


def test_annotate_failure_zero_exit_code() -> None:
    assert annotate_failure("ls", 0, "file1.txt\nfile2.txt") is None


def test_annotate_failure_command_not_found_python() -> None:
    hint = annotate_failure("python script.py", 127, "bash: line 1: python: command not found")
    assert hint is not None
    assert "python3" in hint


def test_annotate_failure_command_not_found_generic() -> None:
    hint = annotate_failure("foobar --flag", 127, "sh: foobar: command not found")
    assert hint is not None
    assert "foobar" in hint


def test_annotate_failure_module_not_found() -> None:
    hint = annotate_failure(
        "python3 run.py",
        1,
        "Traceback (most recent call last):\nModuleNotFoundError: No module named 'pydantic_settings'",
    )
    assert hint is not None
    assert "pydantic_settings" in hint
    assert "virtual environment" in hint or "uv / pip" in hint


def test_annotate_failure_port_in_use() -> None:
    hint = annotate_failure(
        "npm run dev",
        1,
        "Error: listen EADDRINUSE: address already in use :::3000",
    )
    assert hint is not None
    assert "3000" in hint
    assert "lsof" in hint or "PORT" in hint


def test_annotate_failure_git_no_upstream() -> None:
    hint = annotate_failure(
        "git push",
        128,
        "fatal: The current branch feat/subagent has no upstream branch.\nTo push the current branch and set the remote as upstream, use\n\n    git push --set-upstream origin feat/subagent\n",
    )
    assert hint is not None
    assert "git push -u" in hint or "upstream" in hint


def test_annotate_failure_git_clone_timeout() -> None:
    hint = annotate_failure(
        "git clone https://github.com/org/huge-repo.git",
        128,
        "error: RPC failed; curl 18 transfer closed with outstanding read data remaining\nfatal: the remote end hung up unexpectedly",
    )
    assert hint is not None
    assert "depth 1" in hint or "tarball" in hint


def test_annotate_failure_exit_code_fallback() -> None:
    hint = annotate_failure("some_binary", 126, "cannot execute binary file")
    assert hint is not None
    assert "126" in hint
    assert "chmod +x" in hint


def test_annotate_masked_success_pipe() -> None:
    cmd = "pytest tests/ | tail -n 20"
    output = "FAILED tests/unit/test_app.py::test_foo\n= 1 failed, 10 passed in 1.2s ="
    warning = annotate_masked_success(cmd, output)
    assert warning is not None
    assert "Masked Failure Warning" in warning


def test_annotate_masked_success_or_fallback() -> None:
    cmd = "cargo build || echo 'build done'"
    output = "error: could not compile `my_crate` due to 2 previous errors\nbuild done"
    warning = annotate_masked_success(cmd, output)
    assert warning is not None
    assert "Masked Failure Warning" in warning


def test_format_result_integrates_hints() -> None:
    result = {
        "stdout": "",
        "stderr": "bash: python: command not found",
        "exit_code": "127",
    }
    formatted, _, _ = format_result(result, command="python test.py")
    assert "[Auto-Hint]" in formatted
    assert "python3" in formatted
