"""Allowlist pattern scope integration tests."""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.middlewares.approval import add_to_allowlist_if_needed
from myrm_agent_harness.agent.security.approval_flow import AllowlistEntry, get_allowlist


@pytest.fixture(autouse=True)
def _reset_allowlist() -> None:
    import myrm_agent_harness.agent.security.approval_flow as approval_flow

    approval_flow._allowlist = approval_flow.Allowlist()


@pytest.mark.asyncio
async def test_add_pattern_allowlist_and_match_similar_command() -> None:
    allowlist = get_allowlist()

    await add_to_allowlist_if_needed(
        allow_always={"tool": True, "pattern": True},
        user_id="user123",
        permission_type="code_interpreter",
        tool_name="bash_code_execute_tool",
        tool_args_hash="ignored",
        tool_command="npm install lodash",
    )

    assert allowlist.check(
        "user123",
        "code_interpreter",
        "bash_code_execute_tool",
        "different-hash",
        command="npm install --legacy-peer-deps",
    )
    assert not allowlist.check(
        "user123",
        "code_interpreter",
        "bash_code_execute_tool",
        "different-hash",
        command="git status",
    )


@pytest.mark.asyncio
async def test_exact_only_entry_rejects_wrong_hash() -> None:
    allowlist = get_allowlist()

    await allowlist.add(
        "user123",
        AllowlistEntry(
            permission="code_interpreter",
            tool_name="bash_code_execute_tool",
            tool_args_hash="exact-hash",
        ),
    )

    assert allowlist.check(
        "user123",
        "code_interpreter",
        "bash_code_execute_tool",
        "exact-hash",
    )
    assert not allowlist.check(
        "user123",
        "code_interpreter",
        "bash_code_execute_tool",
        "other-hash",
        command="npm install",
    )


@pytest.mark.asyncio
async def test_pattern_allowlist_skips_compound_shell_command() -> None:
    allowlist = get_allowlist()

    await add_to_allowlist_if_needed(
        allow_always={"tool": True, "pattern": True},
        user_id="user123",
        permission_type="code_interpreter",
        tool_name="bash_code_execute_tool",
        tool_command="npm install && rm -rf /",
    )

    assert not allowlist.check(
        "user123",
        "code_interpreter",
        "bash_code_execute_tool",
        command="npm install && rm -rf /",
    )
