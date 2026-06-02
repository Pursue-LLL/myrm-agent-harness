"""Non-zero exit code classification for bash commands.

Many shell tools use non-zero exit codes to convey information rather than errors:
- grep/rg/ag: exit 1 means "no matches found" (valid result)
- diff: exit 1 means "files differ" (valid result)

This module classifies exit codes to prevent Agent from misinterpreting
informational non-zero exits as execution failures.

[INPUT]
- (none)

[OUTPUT]
- classify_exit_code: Classify whether a non-zero exit code is an error or informational.

[POS]
Non-zero exit code semantic classifier. Prevents Agent from misinterpreting
informational shell tool exits (grep no-match, diff has-changes) as errors.
"""

import re

_INFORMATIONAL_EXIT_1_COMMANDS: frozenset[str] = frozenset({
    "grep", "egrep", "fgrep", "rg", "ag", "ack",
    "diff", "colordiff",
})

_COMMAND_PATTERN = re.compile(r"^\s*(?:sudo\s+)?(?:[\w/.-]+/)?(\w[\w.-]*)")


def _extract_base_command(command: str) -> str:
    """Extract the base command name whose exit code determines the pipeline result.

    In a pipeline, exit code comes from the last command (without pipefail).
    Strips sudo prefix and path prefix before matching.

    Examples:
        "grep -r 'TODO' src/"      → "grep"
        "sudo rg 'pattern' ."      → "rg"
        "/usr/bin/diff a b"        → "diff"
        "cat file | grep foo"      → "grep"
        "sort file | diff - other" → "diff"
    """
    last_segment = command.split("|")[-1].strip()
    match = _COMMAND_PATTERN.match(last_segment)
    if match:
        return match.group(1)
    return ""


def classify_exit_code(command: str, exit_code: int, stdout: str) -> bool:
    """Classify whether a non-zero bash exit code represents a real error.

    Args:
        command: The original bash command string.
        exit_code: Process exit code (non-zero).
        stdout: Captured stdout content.

    Returns:
        True if the exit is informational (should be treated as success),
        False if it represents a real error.
    """
    if exit_code == 0:
        return True

    if exit_code != 1:
        return False

    base_cmd = _extract_base_command(command)
    return base_cmd in _INFORMATIONAL_EXIT_1_COMMANDS
