"""Tests for _session_context.py ContextVar safety.

Validates that all ContextVar getters return safe defaults even when
ContextVars have not been explicitly set in the current async context.
"""

from __future__ import annotations

import asyncio

import pytest

from myrm_agent_harness.agent.middlewares._session_context import (
    get_allowed_domains_map,
    get_approval_session,
    get_approval_user_id,
    get_event_logger,
    get_is_subagent,
    get_privacy_policy,
    get_security_config,
    get_subagent_task_id,
    get_terminal_errors,
    get_workspace_root,
    reset_terminal_errors,
    set_allowed_domains_map,
)
from myrm_agent_harness.agent.security.types import PrivacyPolicy


class TestAllowedDomainsMapDefault:
    """get_allowed_domains_map must never return None."""

    def test_default_is_empty_dict(self):
        result = get_allowed_domains_map()
        assert result is not None
        assert isinstance(result, dict)
        assert result == {}

    def test_set_and_get(self):
        test_map = {"example.com": ["GET", "POST"]}
        set_allowed_domains_map(test_map)
        result = get_allowed_domains_map()
        assert result == test_map

    def test_set_none_returns_empty_dict(self):
        """Even if someone passes None, get should return {}."""
        set_allowed_domains_map(None)  # type: ignore[arg-type]
        result = get_allowed_domains_map()
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_isolation_across_tasks(self):
        """ContextVars are isolated between tasks."""
        set_allowed_domains_map({"parent.com": None})

        child_result: dict[str, list[str] | None] = {}

        async def child():
            nonlocal child_result
            child_result = get_allowed_domains_map()

        await asyncio.create_task(child())
        parent_result = get_allowed_domains_map()

        assert parent_result == {"parent.com": None}
        assert child_result == {"parent.com": None}


class TestOtherContextVarDefaults:
    """All ContextVar getters should return safe defaults without explicit set."""

    def test_security_config_default(self):
        assert get_security_config() is None

    def test_workspace_root_default(self):
        assert get_workspace_root() == ""

    def test_approval_session_default(self):
        assert get_approval_session() == ""

    def test_approval_user_id_default(self):
        assert get_approval_user_id() == ""

    def test_event_logger_default(self):
        assert get_event_logger() is None

    def test_is_subagent_default(self):
        assert get_is_subagent() is False

    def test_subagent_task_id_default(self):
        assert get_subagent_task_id() is None

    def test_privacy_policy_default(self):
        policy = get_privacy_policy()
        assert isinstance(policy, PrivacyPolicy)


class TestTerminalErrorsRegistry:
    """Terminal errors registry should auto-create on first access."""

    def test_auto_create(self):
        registry = get_terminal_errors()
        assert registry is not None

    def test_reset(self):
        registry = get_terminal_errors()
        registry.add("test_error")
        reset_terminal_errors()
        registry_after = get_terminal_errors()
        all_errors = registry_after.get_all()
        assert "test_error" not in all_errors
