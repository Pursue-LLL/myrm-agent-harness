"""End-to-end: a user rule and the destructive stop must hold however the command is spelled.

These run the real approval entry point (``evaluate_tool_batch``) because the layers after the policy
evaluation (the destructive stop, the unattended cron resolution) are invisible to ``evaluate_tool_call``.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from myrm_agent_harness.agent.middlewares.approval.batch_processor import evaluate_tool_batch
from myrm_agent_harness.agent.security.channel_presets import build_channel_security_config


def _yolo_config():
    base = build_channel_security_config("web", local_mode=True)
    return replace(base, yolo_mode_enabled=True, yolo_mode_timeout=None, yolo_mode_enabled_at=None)


async def _batch_verdict(config, command: str, *, is_cron: bool) -> str:
    calls = [{"name": "bash_code_execute_tool", "args": {"command": command}, "id": "c1"}]
    approved, denied, _pending = await evaluate_tool_batch(
        calls,
        config,
        is_cron,
        "/tmp",
        "session",
        {0: "hash"},
        None,
        (),
        None,
        is_interactive=not is_cron,
    )
    if approved:
        return "approved"
    return "denied" if denied else "ask"


# Every wrapped form runs the same deletion as its plain form, which the destructive stop already gates.
WRAPPED_DESTRUCTIVE = [
    "sudo rm -rf ./build",
    "nohup rm -rf ./build",
    "env FOO=1 rm -rf ./build",
    "nice -n 5 rm -rf ./build",
    "ls $(rm -rf ./build)",
    "bash -c 'rm -rf ./build'",
    "sudo git clean -fdx",
]


class TestYoloCannotAutoApproveWrappedDestruction:
    @pytest.mark.parametrize("command", WRAPPED_DESTRUCTIVE)
    async def test_wrapped_destructive_is_not_auto_approved(self, command: str) -> None:
        verdict = await _batch_verdict(_yolo_config(), command, is_cron=False)
        assert verdict != "approved", f"YOLO auto-approved {command}"

    async def test_plain_destructive_is_not_auto_approved(self) -> None:
        assert await _batch_verdict(_yolo_config(), "rm -rf ./build", is_cron=False) != "approved"


# A prefix must not lift a user's "permanently blocked" rule in a run where nobody can approve.
DENY_LIST_PREFIXES = ["", "timeout 30 ", "cd /repo && ", "sudo ", "A=1 ", "nohup "]


class TestUserDenyListHoldsThroughPrefixes:
    @pytest.mark.parametrize("prefix", DENY_LIST_PREFIXES)
    async def test_deny_listed_command_is_never_approved_in_cron(self, prefix: str) -> None:
        config = replace(build_channel_security_config("web", local_mode=True), command_denylist=("kubectl delete*",))
        verdict = await _batch_verdict(config, f"{prefix}kubectl delete ns prod", is_cron=True)
        assert verdict == "denied", f"'{prefix}kubectl delete ns prod' escaped the deny list ({verdict})"


# Reading a wrapper chain must not stop at some nesting level: a rule is evaded by depth exactly as it is by
# a single prefix if the inner command is never named. These pin the depth that a real bypass was found at.
class TestDeepNestingCannotEvadeTheGates:
    @pytest.mark.parametrize("depth", [1, 8, 64, 65, 100, 300])
    async def test_deny_listed_command_is_denied_at_any_nesting_depth(self, depth: int) -> None:
        """A user's "permanently blocked" rule holds however many prefixes stand in front of the command."""
        config = replace(build_channel_security_config("web", local_mode=True), command_denylist=("kubectl delete*",))
        verdict = await _batch_verdict(config, "sudo " * depth + "kubectl delete ns prod", is_cron=True)
        assert verdict == "denied", f"{depth} prefixes escaped the deny list ({verdict})"

    @pytest.mark.parametrize("depth", [1, 8, 64, 65, 100, 300])
    async def test_wrapped_destruction_is_not_auto_approved_at_any_nesting_depth(self, depth: int) -> None:
        """YOLO must not auto-approve an irreversible deletion however the command is wrapped."""
        verdict = await _batch_verdict(_yolo_config(), "sudo " * depth + "rm -rf ./build", is_cron=False)
        assert verdict != "approved", f"YOLO auto-approved a deletion behind {depth} prefixes"

    @pytest.mark.parametrize(
        "command",
        [
            "echo $(kubectl delete ns prod)",
            "echo $( kubectl delete ns prod )",
            "echo $(  kubectl delete ns prod  )",
        ],
    )
    async def test_spacing_inside_a_substitution_does_not_evade_the_deny_list(self, command: str) -> None:
        """A rule names a command, not the spaces around it: padding a substitution must not lift it."""
        config = replace(build_channel_security_config("web", local_mode=True), command_denylist=("kubectl delete*",))
        verdict = await _batch_verdict(config, command, is_cron=True)
        assert verdict == "denied", f"'{command}' escaped the deny list ({verdict})"
