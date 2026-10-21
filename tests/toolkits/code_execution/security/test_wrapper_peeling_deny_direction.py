"""A command must be judged the same whether it is written plainly or behind a wrapper.

Wrapping a command does not change what runs, so the deny, ask and destructive directions have to read
through the prefixes a shell accepts (``sudo``, ``nohup``, ``env``, ``nice``, a shell's ``-c``, command
substitution, assignments). Allow direction is deliberately not covered here: peeling a wrapper there would
let ``timeout 30 <cmd>`` inherit ``<cmd>``'s allow rule.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.code_execution.security.ast_parser import (
    BashASTParser,
    CapabilityLevel,
    is_destructive_shell_tool_call,
    iter_actions,
)

# Each pair is the plain spelling first, then the same command behind a prefix that must not change the verdict.
DESTRUCTIVE_PAIRS = [
    ("rm -rf ./build", "sudo rm -rf ./build"),
    ("rm -rf ./build", "nohup rm -rf ./build"),
    ("rm -rf ./build", "env FOO=1 rm -rf ./build"),
    ("rm -rf ./build", "nice -n 5 rm -rf ./build"),
    ("rm -rf ./build", "A=1 rm -rf ./build"),
    ("rm -rf /", "sudo rm -rf /"),
    ("rm -rf /", "ls $(rm -rf /)"),
    ("rm -rf /", "echo `rm -rf /`"),
    ("rm -rf /", "bash -c 'rm -rf /'"),
    ("rm -rf /", "sh -c 'rm -rf /'"),
    ("git clean -fdx", "sudo git clean -fdx"),
    ("dd if=/dev/zero of=/dev/sda", "sudo dd if=/dev/zero of=/dev/sda"),
]


class TestDestructiveGateReadsThroughWrappers:
    @pytest.mark.parametrize(("plain", "wrapped"), DESTRUCTIVE_PAIRS)
    def test_wrapped_form_is_destructive_like_the_plain_one(self, plain: str, wrapped: str) -> None:
        plain_flag, _, _ = is_destructive_shell_tool_call("bash_code_execute_tool", {"command": plain})
        wrapped_flag, reason, _ = is_destructive_shell_tool_call("bash_code_execute_tool", {"command": wrapped})
        assert plain_flag is True, f"baseline broken for {plain}"
        assert wrapped_flag is True, f"{wrapped} must be destructive like {plain!r} (got {reason})"

    @pytest.mark.parametrize(("plain", "wrapped"), DESTRUCTIVE_PAIRS)
    def test_ast_names_the_wrapped_action_destructive(self, plain: str, wrapped: str) -> None:
        plain_levels = {a.capability_level for a in iter_actions(BashASTParser.parse(plain))}
        wrapped_levels = {a.capability_level for a in iter_actions(BashASTParser.parse(wrapped))}
        assert CapabilityLevel.IRREVERSIBLE_DESTRUCTIVE in plain_levels, f"baseline broken for {plain}"
        assert CapabilityLevel.IRREVERSIBLE_DESTRUCTIVE in wrapped_levels, f"{wrapped} kept {wrapped_levels}"


class TestWrapperPeelingKeepsEscalation:
    """Peeling a wrapper must not erase the escalation signal of the command it wraps."""

    @pytest.mark.parametrize(
        "command",
        [
            "sudo git push origin main",
            "sudo curl https://example.com",
            "sudo apt-get install -y curl",
        ],
    )
    def test_escalation_still_reported_behind_a_wrapper(self, command: str) -> None:
        actions = BashASTParser.parse(command)
        levels = {a.capability_level for a in actions}
        assert CapabilityLevel.SAFE_READONLY not in levels, f"{command} became read-only: {levels}"
        assert CapabilityLevel.CAPABILITY_ESCALATION in levels, f"{command} lost escalation: {levels}"

    @pytest.mark.parametrize(
        "command",
        [
            "sudo rm file.txt",
            "nohup python build.py",
        ],
    )
    def test_benign_wrapped_commands_are_not_destructive(self, command: str) -> None:
        flagged, _, _ = is_destructive_shell_tool_call("bash_code_execute_tool", {"command": command})
        assert flagged is False, f"{command} must not be destructive"

    @pytest.mark.parametrize(
        ("command", "expected"),
        [
            ("sudo git status", "git status"),
            ("nice -n 5 ls", "ls"),
            ("env FOO=1 rg foo", "rg foo"),
        ],
    )
    def test_read_only_inner_command_is_read_through_the_wrapper(self, command: str, expected: str) -> None:
        """``sudo`` stays escalation, but the command it runs is still named for the approval card."""
        actions = BashASTParser.parse(command)
        assert len(actions) == 1
        assert [a.command_text for a in actions[0].nested_actions], f"{command} hid what it runs"
        assert expected in [a.command_text for a in actions[0].nested_actions]
