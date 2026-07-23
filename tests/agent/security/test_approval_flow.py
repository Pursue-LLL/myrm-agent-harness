"""Tests for approval_flow module (Allowlist)."""

import pytest

from myrm_agent_harness.agent.security.approval_flow import Allowlist, AllowlistEntry


class TestAllowlist:
    @pytest.fixture
    def allowlist(self):
        return Allowlist()

    def test_check_empty(self, allowlist: Allowlist):
        assert allowlist.check("user1", "shell_exec") is False

    @pytest.mark.asyncio
    async def test_add_and_check(self, allowlist: Allowlist):
        entry = AllowlistEntry(permission="shell_exec")
        await allowlist.add("user1", entry)
        assert allowlist.check("user1", "shell_exec") is True
        assert allowlist.check("user1", "file_read") is False
        assert allowlist.check("user2", "shell_exec") is False

    @pytest.mark.asyncio
    async def test_exact_permission_match(self, allowlist: Allowlist):
        entry = AllowlistEntry(permission="mcp_invoke")
        await allowlist.add("user1", entry)
        assert allowlist.check("user1", "mcp_invoke") is True
        assert allowlist.check("user1", "mcp_list") is False
        assert allowlist.check("user1", "shell_exec") is False

    @pytest.mark.asyncio
    async def test_remove(self, allowlist: Allowlist):
        entry = AllowlistEntry(permission="shell_exec")
        await allowlist.add("user1", entry)
        assert allowlist.check("user1", "shell_exec") is True

        await allowlist.remove("user1", "shell_exec")
        assert allowlist.check("user1", "shell_exec") is False

    @pytest.mark.asyncio
    async def test_multiple_users(self, allowlist: Allowlist):
        await allowlist.add("user1", AllowlistEntry(permission="shell_exec"))
        await allowlist.add("user2", AllowlistEntry(permission="file_read"))

        assert allowlist.check("user1", "shell_exec") is True
        assert allowlist.check("user1", "file_read") is False
        assert allowlist.check("user2", "file_read") is True
        assert allowlist.check("user2", "shell_exec") is False

    @pytest.mark.asyncio
    async def test_pattern_match_checks_command_glob(self, allowlist: Allowlist) -> None:
        entry = AllowlistEntry(
            permission="code_interpreter",
            tool_name="bash_code_execute_tool",
            command_pattern="curl -sS *",
        )
        await allowlist.add("user1", entry)
        assert allowlist.check(
            "user1",
            "code_interpreter",
            "bash_code_execute_tool",
            "any_hash",
            command="curl -sS http://127.0.0.1:9/probe",
        )
        assert not allowlist.check(
            "user1",
            "code_interpreter",
            "bash_code_execute_tool",
            "any_hash",
            command="wget http://127.0.0.1:9/probe",
        )
        assert not allowlist.check(
            "user1",
            "code_interpreter",
            "bash_code_execute_tool",
            "any_hash",
            command="curl -sS http://127.0.0.1:9/probe && rm -rf /",
        )
