"""The capability gate's read-only table and the approval allow list are two different contracts.

``capability_tables.SAFE_READONLY_COMMANDS`` names commands that *only read*, so the capability level of a
read is named truthfully. ``safe_commands.SAFE_COMMANDS`` names commands that *may run without approval*,
which includes workspace-scoped mutation (``touch``, ``mkdir``) and test runners. A command may sit in one
and not the other; what must never happen is one table borrowing the other's entries, because that would
either mislabel a mutation as a read or hand the capability gate commands it was never meant to name.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.code_execution.security.ast_parser import BashASTParser, CapabilityLevel
from myrm_agent_harness.toolkits.code_execution.security.capability_tables import (
    SAFE_READONLY_COMMANDS,
    SAFE_TEST_COMMANDS,
)
from myrm_agent_harness.toolkits.code_execution.security.safe_commands import SAFE_COMMANDS

# Commands the allow list holds that mutate the workspace or run a toolchain; the read-only table must not
# name them. Plain readers the allow list also holds (``date``, ``cal``, ``seq``, ``bc``) legitimately sit in
# both tables and are not listed here.
_NOT_ONLY_READS = frozenset(
    {
        "touch",
        "mkdir",
        "pbcopy",
        "make",
        "cmake",
        "gradle",
        "mvn",
        "ant",
        "pytest",
        "jest",
        "vitest",
        "mocha",
        "phpunit",
        "eslint",
        "ruff",
        "mypy",
        "black",
        "isort",
        "prettier",
        "stylelint",
        "shellcheck",
        "tsc",
        "pyright",
        "biome",
        "flake8",
        "pylint",
    }
)


def test_the_read_only_table_names_no_mutating_or_test_command() -> None:
    borrowed = SAFE_READONLY_COMMANDS & _NOT_ONLY_READS
    assert not borrowed, f"a mutating/test command was labelled as only reading: {sorted(borrowed)}"


def test_the_read_only_table_does_not_borrow_the_allow_list() -> None:
    """The allow list is the wider contract; anything it holds that only reads may be shared, nothing else."""
    assert SAFE_COMMANDS | {"find"} >= SAFE_READONLY_COMMANDS


def test_a_wrapper_is_not_named_only_reads() -> None:
    """``env`` and ``command`` run what follows, so their level is what the inner command's level is."""
    for wrapper in ("env", "command"):
        assert wrapper not in SAFE_READONLY_COMMANDS
        assert wrapper not in SAFE_TEST_COMMANDS


class TestWrapperLevelFollowsTheInnerCommand:
    def test_bare_wrapper_is_workspace_mutation(self) -> None:
        for command in ("env", "command"):
            actions = BashASTParser.parse(command)
            assert actions[0].capability_level == CapabilityLevel.WORKSPACE_MUTATION, command

    def test_read_only_inner_command_stays_read_only(self) -> None:
        for command in ("env ls", "command ls", "env FOO=1 ls"):
            actions = BashASTParser.parse(command)
            assert BashASTParser.has_escalation(actions) is False, command

    def test_destructive_inner_command_still_escalates(self) -> None:
        for command in ("env rm -rf /", "command rm -rf /", "env sudo rm -rf /"):
            actions = BashASTParser.parse(command)
            assert BashASTParser.has_destructive(actions) is True, command
