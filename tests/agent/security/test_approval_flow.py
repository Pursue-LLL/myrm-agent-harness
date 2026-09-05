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

    @pytest.mark.asyncio
    async def test_agent_scope_isolation_prevents_cross_agent_escalation(self, allowlist: Allowlist) -> None:
        # Agent A receives allowlist permission for hosted MCP tool
        entry_a = AllowlistEntry(
            permission="mcp_invoke",
            tool_name="mcp__github__create_issue",
            agent_id="developer_subagent",
        )
        await allowlist.add("user1", entry_a)

        # Developer subagent can execute
        assert allowlist.check(
            "user1",
            "mcp_invoke",
            "mcp__github__create_issue",
            agent_id="developer_subagent",
        ) is True

        # Malicious/untrusted agent B cannot hijack permission (Confused Deputy defense)
        assert allowlist.check(
            "user1",
            "mcp_invoke",
            "mcp__github__create_issue",
            agent_id="untrusted_browser_agent",
        ) is False

        # Global check without agent_id fails against scoped entry
        assert allowlist.check(
            "user1",
            "mcp_invoke",
            "mcp__github__create_issue",
            agent_id=None,
        ) is False

        # Global legacy entry (agent_id=None) matches any agent
        entry_global = AllowlistEntry(
            permission="mcp_invoke",
            tool_name="mcp__weather__get_temp",
            agent_id=None,
        )
        await allowlist.add("user1", entry_global)
        assert allowlist.check(
            "user1",
            "mcp_invoke",
            "mcp__weather__get_temp",
            agent_id="developer_subagent",
        ) is True
        assert allowlist.check(
            "user1",
            "mcp_invoke",
            "mcp__weather__get_temp",
            agent_id="untrusted_browser_agent",
        ) is True

    @pytest.mark.asyncio
    async def test_exact_hash_match_and_clear_user(self, allowlist: Allowlist) -> None:
        entry = AllowlistEntry(
            permission="code_interpreter",
            tool_name="bash_code_execute_tool",
            tool_args_hash="hash_12345",
        )
        await allowlist.add("user1", entry)
        assert allowlist.check("user1", "code_interpreter", "bash_code_execute_tool", "hash_12345") is True
        assert allowlist.check("user1", "code_interpreter", "bash_code_execute_tool", "wrong_hash") is False

        cleared_count = await allowlist.clear_user("user1")
        assert cleared_count == 1
        assert allowlist.check("user1", "code_interpreter", "bash_code_execute_tool", "hash_12345") is False

    @pytest.mark.asyncio
    async def test_store_persistence_and_ttl(self) -> None:
        class InMemoryStore:
            def __init__(self):
                self.entries = {}

            async def load(self, user_id: str):
                return self.entries.get(user_id, [])

            async def save(self, user_id: str, entry: AllowlistEntry):
                self.entries.setdefault(user_id, []).append(entry)

            async def remove(self, user_id: str, permission: str, tool_name=None, tool_args_hash=None, command_pattern=None, agent_id=None):
                if user_id in self.entries:
                    self.entries[user_id] = [
                        e for e in self.entries[user_id]
                        if not (e.permission == permission and (tool_name is None or e.tool_name == tool_name))
                    ]

        store = InMemoryStore()
        al = Allowlist(store=store, ttl_seconds=1.0)
        await al.add("user1", AllowlistEntry(permission="file_read"))
        assert al.check("user1", "file_read") is True

        # Test load_user
        al2 = Allowlist(store=store, ttl_seconds=1.0)
        await al2.load_user("user1")
        assert al2.check("user1", "file_read") is True

    @pytest.mark.asyncio
    async def test_time_bound_scoped_grant_auto_revoke(self, allowlist: Allowlist) -> None:
        import time
        now = time.time()
        # Expired entry (5 seconds in the past)
        expired_entry = AllowlistEntry(
            permission="shell_exec",
            tool_name="bash",
            expires_at=now - 5.0,
        )
        # Active entry (10 seconds in future)
        active_entry = AllowlistEntry(
            permission="email_send",
            tool_name="send_email",
            expires_at=now + 10.0,
        )
        await allowlist.add("user1", expired_entry)
        await allowlist.add("user1", active_entry)

        # Expired entry should be rejected and automatically pruned
        assert allowlist.check("user1", "shell_exec", "bash") is False
        # Active entry should be allowed
        assert allowlist.check("user1", "email_send", "send_email") is True

    @pytest.mark.asyncio
    async def test_time_bound_scoped_grant_persistence_to_store(self) -> None:
        import time

        class TrackingStore:
            def __init__(self):
                self.saved_entries = []

            async def load(self, user_id: str):
                return self.saved_entries

            async def save(self, user_id: str, entry: AllowlistEntry):
                self.saved_entries.append(entry)

            async def remove(self, user_id: str, permission: str, tool_name=None, tool_args_hash=None, command_pattern=None, agent_id=None):
                pass

        store = TrackingStore()
        al = Allowlist(store=store)
        now = time.time()
        timed_entry = AllowlistEntry(permission="email_send", tool_name="send_mail", expires_at=now + 3600.0)
        await al.add("user1", timed_entry)

        assert len(store.saved_entries) == 1
        assert store.saved_entries[0].expires_at == timed_entry.expires_at

    @pytest.mark.asyncio
    async def test_time_bound_entry_exact_and_pattern_expiry(self, allowlist: Allowlist) -> None:
        """Verify expiration applies across granularities (pattern and exact args hash)."""
        import time
        now = time.time()
        pattern_entry = AllowlistEntry(
            permission="shell_exec",
            tool_name="bash_code_execute_tool",
            command_pattern="git status *",
            expires_at=now - 1.0,
        )
        exact_entry = AllowlistEntry(
            permission="shell_exec",
            tool_name="bash_code_execute_tool",
            tool_args_hash="hash_123",
            expires_at=now - 1.0,
        )
        await allowlist.add("user1", pattern_entry)
        await allowlist.add("user1", exact_entry)

        # Both expired entries should be rejected
        assert allowlist.check("user1", "shell_exec", "bash_code_execute_tool", command="git status -s") is False
        assert allowlist.check("user1", "shell_exec", "bash_code_execute_tool", tool_args_hash="hash_123") is False

    @pytest.mark.asyncio
    async def test_session_scoped_allowlist_grant_isolation_and_no_persist(self) -> None:
        """Verify that session-scoped entries match only for the same session and never call store.save()."""
        class MockStore:
            def __init__(self):
                self.saved_entries = []

            async def load(self, user_id: str):
                return []

            async def save(self, user_id: str, entry: AllowlistEntry):
                self.saved_entries.append(entry)

            async def remove(self, *args, **kwargs):
                pass

        store = MockStore()
        al = Allowlist(store=store)

        session_entry = AllowlistEntry(
            permission="shell_exec",
            tool_name="bash",
            session_id="sess_alpha_123",
        )
        await al.add("user1", session_entry)

        # 1. Never persisted to store
        assert len(store.saved_entries) == 0

        # 2. Matches when caller is the same session
        assert al.check("user1", "shell_exec", "bash", session_id="sess_alpha_123") is True

        # 3. Denied when caller is a different session or has no session
        assert al.check("user1", "shell_exec", "bash", session_id="sess_beta_456") is False
        assert al.check("user1", "shell_exec", "bash", session_id=None) is False

        # 4. clear_session purges only that session
        await al.clear_session("user1", "sess_alpha_123")
        assert al.check("user1", "shell_exec", "bash", session_id="sess_alpha_123") is False



