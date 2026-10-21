"""The command-reading walk is bounded: a pathological line cannot hang or overflow the approval path.

``deny_readings`` re-enters on every command a line hands control to, and a line can ask for a great many
of them (hundreds of nested wrappers, or a word that is itself a substitution). Two different things are
bounded, and conflating them is a security bug:

- a *linear* wrapper chain (``sudo``/``timeout``/``time`` repeated any number of times) is peeled in one pass
  to the command it runs, so its length is never a reason to stop reading: the inner command is always
  named, however many prefixes stand in front of it;
- *branching* (a substitution or ``-c`` script inside one) is what costs depth, and is capped by
  ``DENY_WRAPPER_DEPTH`` levels and ``MAX_COMMAND_READINGS`` readings in total.

These tests pin both, so a change that silently truncates a real command fails here rather than in production.
"""

from __future__ import annotations

import time
from fnmatch import fnmatchcase

import pytest

from myrm_agent_harness.core.security.shell_wrapper_peel import (
    DENY_WRAPPER_DEPTH,
    MAX_COMMAND_READINGS,
    deny_readings,
)


def _denied(command: str, glob: str) -> bool:
    return any(fnmatchcase(reading.lower(), glob) for reading in deny_readings(command))


class TestLinearChainIsPeeledToTheBottom:
    @pytest.mark.parametrize("count", [1, 8, 64, 65, 100, 300, 2000])
    def test_a_chain_of_any_length_reaches_the_command_it_runs(self, count: int) -> None:
        """A line built out of prefixes still names the command it runs, so a deny glob cannot be evaded by depth."""
        assert deny_readings("sudo " * count + "kubectl delete ns prod") == ("kubectl delete ns prod",)
        assert _denied("sudo " * count + "kubectl delete ns prod", "kubectl delete*")

    @pytest.mark.parametrize("prefix", ["sudo ", "timeout 30 ", "nohup ", "nice -n 5 ", "env FOO=1 "])
    def test_each_prefix_type_is_peeled_like_the_others(self, prefix: str) -> None:
        assert _denied(prefix * 70 + "kubectl delete ns prod", "kubectl delete*")

    def test_a_chain_costs_one_reading_regardless_of_its_length(self) -> None:
        """The chain collapses to the command at the bottom, so its length does not fan the walk out."""
        assert len(deny_readings("sudo " * 5000 + "rm -rf /")) == 1

    def test_a_very_long_chain_is_read_in_linear_time(self) -> None:
        """Peeling must not re-copy the tail per step: a quadratic walk hangs the approval path on a long chain.

        A 100k-prefix chain is read in well under a second when the peel indexes into one word list; the
        quadratic walk that re-sliced the tail per step took tens of seconds on the same input, so this bound
        separates the two without being close to either on an idle machine.
        """
        chain = "sudo " * 100_000 + "rm -rf /"
        started = time.monotonic()
        assert deny_readings(chain) == ("rm -rf /",)
        assert time.monotonic() - started < 10.0

    @pytest.mark.parametrize(
        ("command", "reading"),
        [
            ("sudo command -v git", "command -v git"),
            ("sudo command -V git", "command -V git"),
            ("sudo time", "time"),
            ("env FOO=1 time", "time"),
            ("sudo timeout 5", "timeout 5"),
            ("nohup command sudo", "sudo"),
        ],
    )
    def test_a_wrapper_that_runs_nothing_is_still_named(self, command: str, reading: str) -> None:
        """The command in front of a wrapper that runs no command is what a deny glob has to see.

        Peel stops at the last prefix it could read through, so the wrapper's own invocation is the reading:
        a rule written for ``command`` or ``timeout`` still fires on ``sudo command -v git``.
        """
        assert reading in deny_readings(command)


class TestFanoutBound:
    def test_a_substitution_in_every_word_is_capped(self) -> None:
        """A command whose every word is its own substitution cannot make the walk unbounded."""
        command = "echo " + " ".join(f"$(id{i})" for i in range(MAX_COMMAND_READINGS * 3))
        assert len(deny_readings(command)) <= MAX_COMMAND_READINGS

    def test_the_command_itself_is_never_a_reading(self) -> None:
        """The caller judges the line as written, so the walk only returns what it hands control to."""
        assert "rm -rf /" in deny_readings("sudo rm -rf /")
        assert "sudo rm -rf /" not in deny_readings("sudo rm -rf /")

    @pytest.mark.parametrize(
        "command",
        [
            "echo $(rm -rf /)",
            "echo $( rm -rf / )",
            "echo $(  rm -rf /  )",
            "echo `rm -rf /`",
        ],
    )
    def test_a_real_payload_survives_the_bounds(self, command: str) -> None:
        """The bounds are far above any line a person writes, so the inner command is always still read."""
        assert "rm -rf /" in deny_readings(command)

    @pytest.mark.parametrize(
        ("command", "glob"),
        [
            ("echo $( kubectl delete ns prod )", "kubectl delete*"),
            ("echo $(  kubectl delete ns prod  )", "kubectl delete*"),
            ("echo `kubectl delete ns prod`", "kubectl delete*"),
            ("echo $($( kubectl delete ns prod ))", "kubectl delete*"),
        ],
    )
    def test_spacing_inside_a_substitution_does_not_hide_the_command(self, command: str, glob: str) -> None:
        """The spaces around the command a substitution runs are not part of the command text a rule matches."""
        assert _denied(command, glob)

    def test_the_branch_bound_is_positive_and_reachable(self) -> None:
        assert DENY_WRAPPER_DEPTH > 0
