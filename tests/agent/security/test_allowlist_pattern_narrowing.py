"""An allow-always pattern covers the command that was approved, not the wrapper it rode in on.

Approving ``timeout 30 pytest -q`` must not mint a ``timeout 30 *`` grant: the next ``timeout 30 rm -rf /``
would then run with no approval at all. The pattern is derived from the command the shell really runs.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.security.command_allowlist_pattern import (
    derive_command_pattern,
    matches_command_pattern,
)


class TestPatternIsDerivedFromTheInnerCommand:
    @pytest.mark.parametrize(
        ("command", "expected"),
        [
            ("timeout 30 pytest -q", "pytest -q *"),
            ("command pytest -q", "pytest -q *"),
            ("command -- npm test", "npm test *"),
            ("time time timeout 5 npm test", "npm test *"),
            ("FOO=1 timeout 30 npm install lodash", "npm install *"),
        ],
    )
    def test_transparent_wrappers_are_peeled_before_deriving(self, command: str, expected: str) -> None:
        assert derive_command_pattern(command) == expected

    def test_an_ununderstood_wrapper_form_is_not_vouched_for(self) -> None:
        assert derive_command_pattern("timeout -k pytest -q") is None

    def test_a_wrapper_that_runs_nothing_derives_no_pattern(self) -> None:
        assert derive_command_pattern("timeout 5") is None

    @pytest.mark.parametrize("command", ["npm install lodash", "ls -la", "args=timeout npm test"])
    def test_a_command_without_a_wrapper_is_derived_as_written(self, command: str) -> None:
        assert derive_command_pattern(command) is not None


class TestApprovingOneCommandDoesNotApproveAnother:
    def test_pytest_approval_does_not_cover_rm_behind_the_same_wrapper(self) -> None:
        pattern = derive_command_pattern("timeout 30 pytest -q")
        assert matches_command_pattern(pattern, "timeout 30 rm -rf /") is False

    def test_a_plain_command_is_still_read_as_written(self) -> None:
        """A command with no wrapper keeps matching its own pattern, so ordinary grants are unchanged."""
        assert matches_command_pattern("npm install *", "npm install --legacy-peer-deps") is True
        assert matches_command_pattern("ls -la *", "ls -la /tmp") is True

    def test_a_command_wrapper_does_not_cover_another_program(self) -> None:
        pattern = derive_command_pattern("command pytest -q")
        assert matches_command_pattern(pattern, "command rm -rf /") is False
