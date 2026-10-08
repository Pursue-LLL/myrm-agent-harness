"""SKILL.md hook parser: tool filters, per-entry isolation, and honest failure modes."""

from __future__ import annotations

import logging

import pytest

from myrm_agent_harness.agent.hooks.executor import _matches_hook
from myrm_agent_harness.agent.hooks.skill_parser import parse_hooks_from_skill_md
from myrm_agent_harness.agent.hooks.types import (
    CommandHookDefinition,
    HookEvent,
    HttpHookDefinition,
)

_PARSER_LOGGER = "myrm_agent_harness.agent.hooks.skill_parser"


def _skill(*entries: str, event: str = "PreToolUse") -> str:
    body = "\n".join(f"    - {entry}" for entry in entries)
    return f"---\nname: probe\ndescription: probe\nhooks:\n  {event}:\n{body}\n---\n# probe\n"


def _only_hook(content: str) -> CommandHookDefinition | HttpHookDefinition:
    ((_, hook),) = parse_hooks_from_skill_md(content)[0]
    assert isinstance(hook, CommandHookDefinition | HttpHookDefinition)
    return hook


def _tool_call(name: str) -> dict[str, object]:
    return {"tool_name": name}


# --- tool filter -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("tools", "expected"),
    [
        ("[bash_*]", "bash_*"),
        ("[bash_*, write_file_tool]", "bash_*|write_file_tool"),
        ("'bash_*, write_file_tool'", "bash_*|write_file_tool"),
        ("bash_*", "bash_*"),
        ("[]", ""),
    ],
)
def test_tools_become_one_matcher_with_alternatives(tools: str, expected: str) -> None:
    hook = _only_hook(_skill(f"script: 'echo hi'\n      tools: {tools}"))

    assert hook.matcher == expected


def test_listed_tools_filter_to_exactly_those_tools() -> None:
    hook = _only_hook(_skill("script: 'echo hi'\n      tools: [bash_code_execute_tool, write_file_tool]"))

    assert _matches_hook(hook, _tool_call("bash_code_execute_tool"))
    assert _matches_hook(hook, _tool_call("write_file_tool"))
    assert not _matches_hook(hook, _tool_call("read_file_tool"))


def test_wildcard_alternatives_match_each_pattern() -> None:
    hook = CommandHookDefinition(command="echo hi", matcher="bash_*|web_*")

    assert _matches_hook(hook, _tool_call("bash_code_execute_tool"))
    assert _matches_hook(hook, _tool_call("web_fetch_tool"))
    assert not _matches_hook(hook, _tool_call("file_read_tool"))


def test_without_tools_the_hook_sees_every_tool() -> None:
    hook = _only_hook(_skill("script: 'echo hi'"))

    assert _matches_hook(hook, _tool_call("anything_tool"))


@pytest.mark.parametrize("tools", ["5", "[1, 2]", "{a: b}"])
def test_malformed_tools_skip_the_entry_instead_of_widening_it(tools: str, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger=_PARSER_LOGGER):
        hooks, _ = parse_hooks_from_skill_md(_skill(f"script: 'echo hi'\n      tools: {tools}"))

    assert hooks == []
    assert any("Skipping invalid" in record.getMessage() for record in caplog.records)


# --- per-entry isolation ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_field", ["timeout: 0", "timeout: 9999", "timeout: abc", "timeout: true", "timeout: 0.4"])
def test_invalid_timeout_drops_only_that_entry(bad_field: str, caplog: pytest.LogCaptureFixture) -> None:
    content = _skill(f"script: 'echo bad'\n      {bad_field}", "script: 'echo good'")

    with caplog.at_level(logging.WARNING, logger=_PARSER_LOGGER):
        hooks, _ = parse_hooks_from_skill_md(content)

    assert [hook.command for _, hook in hooks if isinstance(hook, CommandHookDefinition)] == ["echo good"]
    assert any("Skipping invalid" in record.getMessage() for record in caplog.records)


def test_non_string_script_drops_only_that_entry() -> None:
    hooks, _ = parse_hooks_from_skill_md(_skill("script: 123", "script: 'echo good'"))

    assert [hook.command for _, hook in hooks if isinstance(hook, CommandHookDefinition)] == ["echo good"]


def test_valid_timeout_is_kept() -> None:
    assert _only_hook(_skill("script: 'echo hi'\n      timeout: 25")).timeout_seconds == 25


def test_entry_declaring_both_script_and_url_uses_the_url(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger=_PARSER_LOGGER):
        hook = _only_hook(_skill("script: 'echo hi'\n      url: https://example.com/hook"))

    assert isinstance(hook, HttpHookDefinition)
    assert any("both script and url" in record.getMessage() for record in caplog.records)


# --- failure mode ----------------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["fail_closed", "FAIL_CLOSED", "fail-closed", "closed", "'  Fail-Closed '"])
def test_every_fail_closed_spelling_blocks_on_failure(mode: str) -> None:
    assert _only_hook(_skill(f"script: 'echo hi'\n      failure_mode: {mode}")).block_on_failure is True


@pytest.mark.parametrize("mode", ["fail_open", "fail-open", "open"])
def test_fail_open_spellings_do_not_block(mode: str, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger=_PARSER_LOGGER):
        hook = _only_hook(_skill(f"script: 'echo hi'\n      failure_mode: {mode}"))

    assert hook.block_on_failure is False
    assert [record for record in caplog.records if record.name == _PARSER_LOGGER] == []


def test_absent_failure_mode_does_not_block() -> None:
    assert _only_hook(_skill("script: 'echo hi'")).block_on_failure is False


@pytest.mark.parametrize("mode", ["block", "true", "fail_closd"])
def test_unknown_failure_mode_is_reported_not_silent(mode: str, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger=_PARSER_LOGGER):
        hook = _only_hook(_skill(f"script: 'echo hi'\n      failure_mode: {mode}"))

    assert hook.block_on_failure is False
    assert any("Unknown failure_mode" in record.getMessage() for record in caplog.records)


# --- events ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("alias", "event"),
    [
        ("BeforeToolUse", HookEvent.PRE_TOOL_USE),
        ("PreToolUse", HookEvent.PRE_TOOL_USE),
        ("AfterToolUse", HookEvent.POST_TOOL_USE),
        ("PostToolUse", HookEvent.POST_TOOL_USE),
        ("PostToolUseFailure", HookEvent.POST_TOOL_USE_FAILURE),
        ("SessionStart", HookEvent.SESSION_START),
        ("SessionEnd", HookEvent.SESSION_END),
        ("Stop", HookEvent.SESSION_END),
    ],
)
def test_recognised_event_aliases(alias: str, event: HookEvent) -> None:
    ((parsed_event, _),) = parse_hooks_from_skill_md(_skill("script: 'echo hi'", event=alias))[0]

    assert parsed_event == event


def test_event_that_never_fires_is_reported_instead_of_silently_accepted(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger=_PARSER_LOGGER):
        hooks, _ = parse_hooks_from_skill_md(_skill("script: 'echo hi'", event="PreCompact"))

    assert hooks == []
    assert any("Unknown hook type: PreCompact" in record.getMessage() for record in caplog.records)
