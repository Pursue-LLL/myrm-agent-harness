"""Tests for the SAFE allow-list data: argument guards and transparent wrappers."""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.code_execution.security import safe_commands
from myrm_agent_harness.toolkits.code_execution.security.safe_commands import (
    SAFE_COMMANDS,
    TRANSPARENT_WRAPPERS,
    has_unsafe_arguments,
    is_guarded,
    unwrap_transparent_wrapper,
)


class TestAllowList:
    def test_wrappers_are_not_blanket_safe(self) -> None:
        """A wrapper is SAFE only through the command it runs, so it must not sit in the plain allow-list."""
        assert not TRANSPARENT_WRAPPERS & SAFE_COMMANDS

    def test_guards_exist_only_for_safe_commands(self) -> None:
        """A guard on a command that is not auto-approved anyway would be dead policy."""
        assert set(safe_commands._GUARDS) <= SAFE_COMMANDS

    def test_guarded_commands(self) -> None:
        guarded = {name for name in SAFE_COMMANDS if is_guarded(name)}
        assert guarded == {
            "rg",
            "fd",
            "ag",
            "fzf",
            "sort",
            "uniq",
            "tree",
            "yq",
            "nvm",
            "rbenv",
            "pyenv",
            "fnm",
            "volta",
        }


class TestExecutingFlags:
    @pytest.mark.parametrize(
        ("base", "args"),
        [
            ("rg", ["--pre", "./x.sh", "foo"]),
            ("rg", ["--pre=./x.sh", "foo"]),
            ("rg", ["foo", "--hostname-bin", "x"]),
            ("rg", ["--pr=bash", "foo"]),
            ("fd", ["-x", "rm", "{}"]),
            ("fd", ["--exec", "rm"]),
            ("fd", ["-X", "rm"]),
            ("fd", ["--exec-batch", "rm"]),
            ("fd", ["--exec-b", "rm"]),
            ("fd", ["-HIx", "rm"]),
            ("ag", ["--pager", "x", "foo"]),
            ("ag", ["--pag=x", "foo"]),
            ("fzf", ["--bind", "enter:execute(rm x)"]),
            ("fzf", ["--preview", "cat {}"]),
            ("fzf", ["--with-shell", "bash -c"]),
        ],
    )
    def test_flag_that_runs_a_program_is_unsafe(self, base: str, args: list[str]) -> None:
        assert has_unsafe_arguments(base, args) is True

    @pytest.mark.parametrize(
        ("base", "args"),
        [
            ("rg", ["foo", "src"]),
            ("rg", ["-n", "--pretty", "--hidden", "foo"]),
            ("rg", ["--pre-glob=*.gz", "foo"]),
            ("rg", ["--", "--pre"]),
            ("fd", ["name"]),
            ("fd", ["--extension", "py", "--exclude", "node_modules", "-H", "-I", "-t", "f"]),
            ("ag", ["--passthrough", "foo"]),
            ("fzf", ["--border", "--height=40%", "--header=x", "--preview-window=up"]),
        ],
    )
    def test_ordinary_flags_stay_safe(self, base: str, args: list[str]) -> None:
        assert has_unsafe_arguments(base, args) is False


class TestFileWritingArguments:
    @pytest.mark.parametrize(
        ("base", "args"),
        [
            ("sort", ["-o", "out.txt", "in.txt"]),
            ("sort", ["in.txt", "-o", "out.txt"]),
            ("sort", ["-nosorted.txt", "in.txt"]),
            ("sort", ["-rno", "out.txt"]),
            ("sort", ["--output=out.txt", "in.txt"]),
            ("sort", ["--out=out.txt", "in.txt"]),
            ("sort", ["--o=out.txt", "in.txt"]),
            ("sort", ["--compress-program=sh", "in.txt"]),
            ("sort", ["--co=sh", "in.txt"]),
            ("uniq", ["in.txt", "out.txt"]),
            ("uniq", ["-c", "in.txt", "out.txt"]),
            ("tree", ["-o", "listing.txt"]),
            ("yq", ["-i", ".a = 1", "f.yaml"]),
            ("yq", ["--inplace", ".a = 1", "f.yaml"]),
            ("yq", ["--in", ".a = 1", "f.yaml"]),
        ],
    )
    def test_argument_that_writes_a_file_is_unsafe(self, base: str, args: list[str]) -> None:
        assert has_unsafe_arguments(base, args) is True

    @pytest.mark.parametrize(
        ("base", "args"),
        [
            ("sort", ["in.txt"]),
            ("sort", ["-rn", "-k", "2", "in.txt"]),
            ("sort", ["--check", "--unique", "in.txt"]),
            ("sort", ["--", "-o"]),
            ("uniq", []),
            ("uniq", ["-c"]),
            ("uniq", ["in.txt"]),
            ("uniq", ["-", "--"]),
            ("tree", ["-L", "2", "-a"]),
            ("yq", [".a", "f.yaml"]),
            ("yq", ["-ojson", ".a", "f.yaml"]),
            ("yq", ["--indent", "2", ".a"]),
        ],
    )
    def test_read_only_use_stays_safe(self, base: str, args: list[str]) -> None:
        assert has_unsafe_arguments(base, args) is False


class TestVersionManagers:
    @pytest.mark.parametrize("base", ["nvm", "rbenv", "pyenv", "fnm", "volta"])
    def test_exec_and_run_run_any_command(self, base: str) -> None:
        assert has_unsafe_arguments(base, ["exec", "rm", "-rf", "x"]) is True
        assert has_unsafe_arguments(base, ["run", "x"]) is True
        assert has_unsafe_arguments(base, ["--verbose", "run", "x"]) is True

    @pytest.mark.parametrize("base", ["nvm", "rbenv", "pyenv", "fnm", "volta"])
    def test_listing_and_lookup_stay_safe(self, base: str) -> None:
        for args in (["versions"], ["version"], ["which", "python"], ["list"], []):
            assert has_unsafe_arguments(base, args) is False


class TestUnguardedCommands:
    @pytest.mark.parametrize("base", ["ls", "cat", "grep", "echo", "pytest", "unknown-tool"])
    def test_commands_without_guard_have_no_unsafe_arguments(self, base: str) -> None:
        assert is_guarded(base) is False
        assert has_unsafe_arguments(base, ["--pre", "-o", "-x", "exec"]) is False


class TestUnwrapTransparentWrapper:
    @pytest.mark.parametrize(
        ("base", "args", "expected"),
        [
            ("timeout", ["30", "rm", "-rf", "x"], ["rm", "-rf", "x"]),
            ("timeout", ["1.5s", "ls"], ["ls"]),
            ("timeout", ["-s", "KILL", "30", "ls"], ["ls"]),
            ("timeout", ["-k", "5", "30", "ls"], ["ls"]),
            ("timeout", ["--signal=KILL", "--kill-after=5", "30", "ls"], ["ls"]),
            ("timeout", ["--foreground", "--preserve-status", "-v", "30", "ls"], ["ls"]),
            ("timeout", ["5"], []),
            ("time", [], []),
            ("time", ["ls", "-la"], ["ls", "-la"]),
            ("time", ["-p", "ls"], ["ls"]),
            ("time", ["--", "ls"], ["ls"]),
            ("command", ["ls"], ["ls"]),
            ("command", ["-p", "ls"], ["ls"]),
            ("command", ["--", "ls"], ["ls"]),
            ("command", ["-v", "git"], []),
            ("command", ["-V", "git"], []),
            ("command", [], []),
        ],
    )
    def test_returns_the_command_that_runs(self, base: str, args: list[str], expected: list[str]) -> None:
        assert unwrap_transparent_wrapper(base, args) == expected

    @pytest.mark.parametrize(
        ("base", "args"),
        [
            ("timeout", []),
            ("timeout", ["ls"]),
            ("timeout", ["soon", "ls"]),
            ("timeout", ["--unknown", "5", "ls"]),
            ("timeout", ["-fp", "5", "ls"]),
            ("timeout", ["-s"]),
            ("time", ["-l", "ls"]),
            ("time", ["-o", "out", "ls"]),
            ("command", ["-x", "ls"]),
            ("command", ["-p", "-v", "ls"]),
        ],
    )
    def test_unknown_form_is_not_understood(self, base: str, args: list[str]) -> None:
        assert unwrap_transparent_wrapper(base, args) is None
