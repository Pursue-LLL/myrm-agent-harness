"""The wrapper peel reads each prefix form, shell ``-c`` script and substitution the way bash does.

The deny, ask and destructive directions all rest on this one reading, so every prefix spelling that the
peel understands is pinned here: a form it silently fails to read is a command a deny rule would not see.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.core.security.shell_wrapper_peel import (
    deny_readings,
    direct_command_readings,
    substitution_bodies,
)


class TestPrefixForms:
    @pytest.mark.parametrize(
        ("command", "reading"),
        [
            # ``--`` ends the prefix's own options; the command after it is what runs.
            ("sudo -- rm -rf /", "rm -rf /"),
            ("sudo -u root -- rm -rf /", "rm -rf /"),
            # A value-taking flag that carries its value glued on.
            ("sudo --user=root rm -rf /", "rm -rf /"),
            ("timeout -s KILL 30 rm -rf /", "rm -rf /"),
            ("timeout -k 5 30 rm -rf /", "rm -rf /"),
            ("timeout --signal=TERM 30 rm -rf /", "rm -rf /"),
            ("nice -n 5 rm -rf /", "rm -rf /"),
            ("stdbuf -oL rm -rf /", "rm -rf /"),
            ("xargs -n 1 rm -rf /", "rm -rf /"),
        ],
    )
    def test_prefix_options_are_read_through(self, command: str, reading: str) -> None:
        assert reading in deny_readings(command)

    @pytest.mark.parametrize(
        "command",
        [
            # A prefix that runs no command is left where it is; nothing runs and the peel stops.
            "timeout --unknown 5 rm x",
            "sudo -v",
            "ionice -p123 ls",
            "sudo -k",
        ],
    )
    def test_a_prefix_that_runs_nothing_is_not_read_through(self, command: str) -> None:
        assert deny_readings(command) == ()

    @pytest.mark.parametrize(
        ("command", "reading"),
        [
            ("eval rm -rf /", "rm -rf /"),
            ('eval "rm -rf /"', "rm -rf /"),
            ("eval -- rm -rf /", "rm -rf /"),
            ("bash -c 'rm -rf /'", "rm -rf /"),
            ("bash --noprofile -c 'rm -rf /'", "rm -rf /"),
            ("bash -lc 'rm -rf /'", "rm -rf /"),
            ("sh -c 'rm -rf /'", "rm -rf /"),
            ("zsh -c 'rm -rf /'", "rm -rf /"),
        ],
    )
    def test_a_shell_script_or_eval_is_read_as_its_own_line(self, command: str, reading: str) -> None:
        assert reading in deny_readings(command)

    @pytest.mark.parametrize("command", ["bash script.sh", "bash", "bash --version", "sh -s"])
    def test_a_shell_reading_a_file_is_not_read_as_one(self, command: str) -> None:
        """A ``-c`` script's text is readable; a file the shell reads is not, so nothing is vouched for."""
        assert deny_readings(command) == ()


class TestSubstitutionScan:
    @pytest.mark.parametrize("command", ["echo $(", "echo $(echo no-close", "echo `", "echo `no-close"])
    def test_an_unclosed_substitution_yields_nothing(self, command: str) -> None:
        assert substitution_bodies(command) == []

    def test_a_backslash_escape_is_not_a_substitution(self) -> None:
        assert substitution_bodies(r"echo \$(ls)") == []

    def test_a_single_quoted_substitution_is_literal(self) -> None:
        assert substitution_bodies("echo '$(ls)'") == []

    def test_a_quote_inside_a_body_does_not_end_it(self) -> None:
        """``$(echo ')')`` is one substitution; the ``)`` inside the quotes does not close it."""
        assert substitution_bodies("echo $(echo ')')") == ["echo ')'"]

    def test_an_escaped_backtick_does_not_end_a_backtick_substitution(self) -> None:
        assert substitution_bodies(r"echo `a\`b`") == [r"a\`b"]

    def test_arithmetic_is_not_a_command_but_a_nested_substitution_is(self) -> None:
        assert substitution_bodies("echo $((1 + 2))") == []
        assert substitution_bodies("echo $(( $(date +%s) + 1 ))") == ["date +%s"]


class TestDirectReadings:
    def test_a_chain_that_reaches_a_command_names_it(self) -> None:
        assert "rm -rf /" in direct_command_readings("sudo timeout 30 rm -rf /")

    def test_an_assignment_only_prefix_reads_through_to_its_command(self) -> None:
        assert "rm -rf /" in direct_command_readings("FOO=1 rm -rf /")

    def test_a_plain_command_has_no_inner_reading(self) -> None:
        """Nothing hands control onward, so the caller's own reading is the only one."""
        assert direct_command_readings("ls -la") == ()
