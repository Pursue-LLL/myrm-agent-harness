"""A user deny glob and a ruleset pattern judge the command the shell runs, however it is spelled.

A rule written for ``kubectl delete*`` or ``rm *`` must fire when the same command is wrapped
(``sudo``, ``nohup``, ``env``, an assignment), chained behind another command, or handed to a shell
``-c``. What must NOT change is the allow direction: looking through a wrapper can only add a stricter
verdict, never widen an allow.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.security.command_rules import check_command_denylist, judge_command
from myrm_agent_harness.agent.security.types import PermissionAction, PermissionRule

ALLOW, ASK, DENY = PermissionAction.ALLOW, PermissionAction.ASK, PermissionAction.DENY

DENYLIST_PREFIXES = [
    "",
    "timeout 30 ",
    "cd /repo && ",
    "sudo ",
    "A=1 ",
    "nohup ",
    "env FOO=1 ",
    "nice -n 5 ",
    "timeout 30 sudo ",
]


class TestDenylistHoldsThroughPrefixes:
    @pytest.mark.parametrize("prefix", DENYLIST_PREFIXES)
    def test_a_deny_glob_matches_the_command_the_prefix_runs(self, prefix: str) -> None:
        action, reason = check_command_denylist(
            "code_interpreter", {"command": f"{prefix}kubectl delete ns prod"}, ("kubectl delete*",)
        )
        assert action is DENY, f"'{prefix}kubectl delete ns prod' escaped the deny list ({reason})"

    @pytest.mark.parametrize(
        "command",
        [
            "bash -c 'kubectl delete ns prod'",
            "sh -c 'kubectl delete ns prod'",
            "eval 'kubectl delete ns prod'",
            "ls $(kubectl delete ns prod)",
            "echo `kubectl delete ns prod`",
        ],
    )
    def test_a_deny_glob_matches_a_command_handed_to_another_shell(self, command: str) -> None:
        action, _ = check_command_denylist("code_interpreter", {"command": command}, ("kubectl delete*",))
        assert action is DENY, f"{command} escaped the deny list"

    def test_an_unrelated_glob_does_not_fire(self) -> None:
        action, _ = check_command_denylist(
            "code_interpreter", {"command": "sudo kubectl get pods"}, ("kubectl delete*",)
        )
        assert action is None


def _resolve(*rules: PermissionRule):
    def resolve(text: str) -> PermissionRule:
        for rule in rules:
            if rule.pattern == "*" or text.startswith(rule.pattern.rstrip("*").rstrip()):
                return rule
        return PermissionRule("code_interpreter", "*", ASK)

    return resolve


class TestRulesetPatternsSeeThroughPrefixes:
    @pytest.mark.parametrize(
        "command",
        [
            "rm -rf build",
            "sudo rm -rf build",
            "nohup rm -rf build",
            "env FOO=1 rm -rf build",
            "nice -n 5 rm -rf build",
            "A=1 rm -rf build",
            "bash -c 'rm -rf build'",
            "ls $(rm -rf build)",
        ],
    )
    def test_a_deny_pattern_still_fires(self, command: str) -> None:
        verdict = judge_command(command, _resolve(PermissionRule("code_interpreter", "rm ", DENY)))
        assert verdict.action is DENY, f"{command} -> {verdict.action}"

    @pytest.mark.parametrize(
        "command",
        ["sudo ls", "nohup ls", "env FOO=1 ls", "A=1 ls", "timeout 30 ls"],
    )
    def test_looking_through_a_wrapper_does_not_widen_an_allow(self, command: str) -> None:
        """The wrapped command matches ``ls``, but a wider reading must not turn that into a DENY of its own."""
        verdict = judge_command(command, _resolve(PermissionRule("code_interpreter", "ls ", ALLOW)))
        assert verdict.action is not DENY, command

    def test_an_ask_inside_a_wrapper_still_blocks_the_auto_allow(self) -> None:
        verdict = judge_command("sudo rm -rf build", _resolve(PermissionRule("code_interpreter", "rm ", ASK)))
        assert verdict.action is ASK
        assert verdict.classifier_may_allow is False
