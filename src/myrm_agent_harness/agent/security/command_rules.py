"""Rules the permission engine applies to the command line of shell tools.

[INPUT]
- Tool input of a command-bearing tool: ``command`` (bash tool) or ``data`` (text typed into a running process)
- core.security.shell_command_lexer: where each command of a line starts and ends
- agent.security.command_allowlist_pattern::is_compound_shell_command (POS: more than one plain command)

[OUTPUT]
- COMMAND_BEARING_PERMISSIONS: permission types whose tool input carries command text
- command_text(): the text a shell tool is about to run
- check_command_denylist(): user-defined deny globs over that text (Layer 2a.5, YOLO-proof)
- CommandVerdict / judge_command(): the ruleset's decision for a line, with each pattern rule scoped to the one
  plain command it was written for

[POS]
Pure helpers of ``engine.py``: the engine owns the order of the layers, this module owns what a shell command
line means to a rule, so a rule sees the same command the shell will run.
"""

from __future__ import annotations

from collections.abc import Callable
from fnmatch import fnmatch
from typing import NamedTuple

from myrm_agent_harness.agent.security.command_allowlist_pattern import (
    is_compound_shell_command,
)
from myrm_agent_harness.agent.security.types import PermissionAction, PermissionRule
from myrm_agent_harness.core.security.shell_command_lexer import (
    split_command_spans,
    strip_comments,
)

COMMAND_BEARING_PERMISSIONS = frozenset({"shell_exec", "code_interpreter"})

_SEVERITY = {
    PermissionAction.ALLOW: 0,
    PermissionAction.ASK: 1,
    PermissionAction.DENY: 2,
}


def command_text(tool_input: dict[str, object]) -> str:
    """The text a shell tool is about to run: its ``command``, else ``code``, else the ``data`` typed into a process."""
    return str(tool_input.get("command", "") or tool_input.get("code", "") or tool_input.get("data", "")).strip()


def check_command_denylist(
    permission: str,
    tool_input: dict[str, object],
    command_denylist: tuple[str, ...],
) -> tuple[PermissionAction | None, str]:
    """Deny shell/code_interpreter calls whose command matches a user-defined glob.

    Layer 2a.5: fires after ShellCommandAnalyzer (hardline), before URL scheme
    check. Uses case-insensitive fnmatch so ``git push --force*`` matches
    ``Git Push --Force origin main``.  YOLO cannot bypass this layer because
    ``batch_processor.evaluate_tool_batch`` calls ``evaluate_tool_call`` and
    honours DENY even under YOLO mode.
    """
    if permission not in COMMAND_BEARING_PERMISSIONS or not command_denylist:
        return None, ""
    command = command_text(tool_input)
    if not command:
        return None, ""
    command_lower = command.lower()
    for pattern in command_denylist:
        if fnmatch(command_lower, pattern.lower()):
            return (
                PermissionAction.DENY,
                f"Blocked by command denylist rule: {pattern}",
            )
    return None, ""


def command_parts(command: str) -> tuple[str, ...]:
    """The commands of a line as the shell runs them: chained commands apart, comments dropped."""
    parts = (strip_comments(command[start:end]).strip() for start, end in split_command_spans(command))
    return tuple(part for part in parts if part)


class CommandVerdict(NamedTuple):
    """The ruleset's decision for a command line.

    ``classifier_may_allow`` is False when a pattern rule asked on purpose: the classifier that lets read-only
    commands through must not turn that ASK into an ALLOW.
    """

    action: PermissionAction
    classifier_may_allow: bool


def judge_command(command: str, resolve: Callable[[str], PermissionRule]) -> CommandVerdict:
    """Decide a command line from the rules that govern each of its commands.

    A pattern is written for one command, and the shell runs whatever is chained to it as well, so:

    - every command of the line is matched on its own and the strictest decision wins (DENY, then ASK, then
      ALLOW): ``rm *`` has to catch ``cd build && rm -rf x``;
    - an ALLOW from a pattern rule counts only for a single plain command: ``docker *`` must not cover
      ``docker build . ; rm -rf ~`` or ``docker build . > ~/.bashrc``, which a glob over the whole line matches.
      A blanket ``*`` ALLOW is the decision for every command and keeps covering the whole line;
    - an ASK from a pattern rule is final: the read-only classifier does not override it.

    ``resolve`` returns the rule that governs one command text.
    """
    parts = command_parts(command)
    chained = len(parts) > 1 or is_compound_shell_command(command)
    action = PermissionAction.ALLOW
    classifier_may_allow = True
    for part in parts or ("*",):
        rule = resolve(part)
        part_action = rule.action
        if rule.pattern != "*":
            if part_action is PermissionAction.ALLOW and chained:
                part_action = PermissionAction.ASK
            elif part_action is PermissionAction.ASK:
                classifier_may_allow = False
        if _SEVERITY[part_action] > _SEVERITY[action]:
            action = part_action
    return CommandVerdict(action, classifier_may_allow)
