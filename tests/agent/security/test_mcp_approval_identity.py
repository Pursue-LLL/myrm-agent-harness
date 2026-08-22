"""Tests for Hosted MCP Approval Identity Scope and Confused Deputy Attack prevention."""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.security.approval_flow import Allowlist, AllowlistEntry
from myrm_agent_harness.agent.security.mcp_approval_identity import (
    ApprovalIdentityScope,
    is_mcp_permission_or_tool,
    validate_mcp_approval_identity_scope,
)


class TestApprovalIdentityScope:
    def test_scope_creation_and_matches(self):
        scope = ApprovalIdentityScope(
            user_id="sandbox",
            agent_id="code_assistant",
            session_id="session_123",
            tenant_id="tenant_abc",
            is_hosted_mcp=True,
        )
        assert scope.user_id == "sandbox"
        assert scope.agent_id == "code_assistant"
        assert scope.session_id == "session_123"
        assert scope.tenant_id == "tenant_abc"
        assert scope.is_hosted_mcp is True

        assert scope.matches_agent("code_assistant") is True
        assert scope.matches_agent("other_agent") is False
        assert scope.matches_agent(None) is False

    def test_empty_agent_scope_matches_anything(self):
        scope = ApprovalIdentityScope(user_id="sandbox", agent_id=None)
        assert scope.matches_agent("any_agent") is True
        assert scope.matches_agent(None) is True


class TestIsMcpPermissionOrTool:
    def test_mcp_permission_types(self):
        assert is_mcp_permission_or_tool("mcp_invoke") is True
        assert is_mcp_permission_or_tool("shell_exec") is False
        assert is_mcp_permission_or_tool("code_interpreter") is False

    def test_mcp_tool_names(self):
        assert is_mcp_permission_or_tool("tool_exec", "mcp__github__create_issue") is True
        assert is_mcp_permission_or_tool("tool_exec", "mcp_slack_send") is True
        assert is_mcp_permission_or_tool("tool_exec", "bash_code_execute_tool") is False
        assert is_mcp_permission_or_tool("tool_exec", None) is False


class TestValidateMcpApprovalIdentityScope:
    def test_scoped_entry_requires_matching_agent(self):
        assert validate_mcp_approval_identity_scope(
            entry_agent_id="agent_a",
            current_agent_id="agent_a",
            permission_type="mcp_invoke",
        ) is True

        assert validate_mcp_approval_identity_scope(
            entry_agent_id="agent_a",
            current_agent_id="agent_b",
            permission_type="mcp_invoke",
        ) is False

        assert validate_mcp_approval_identity_scope(
            entry_agent_id="agent_a",
            current_agent_id=None,
            permission_type="mcp_invoke",
        ) is False

    def test_non_mcp_tool_validation(self):
        # Non-MCP tools with entry_agent_id=None allow any agent
        assert validate_mcp_approval_identity_scope(
            entry_agent_id=None,
            current_agent_id="agent_x",
            permission_type="shell_exec",
        ) is True


@pytest.mark.asyncio
class TestConfusedDeputyAdversarialScenarios:
    """Adversarial security validation against Confused Deputy / Scope Pollution attacks."""

    async def test_cross_agent_mcp_permission_hijacking_rejected(self):
        allowlist = Allowlist()
        user_id = "sandbox"

        # Step 1: User explicitly approves Agent A to execute dangerous hosted MCP tool
        await allowlist.add(
            user_id,
            AllowlistEntry(
                permission="mcp_invoke",
                tool_name="mcp__stripe__charge_customer",
                agent_id="finance_lead_agent",
            ),
        )

        # Step 2: Agent A executes - verified & permitted
        assert allowlist.check(
            user_id,
            "mcp_invoke",
            "mcp__stripe__charge_customer",
            agent_id="finance_lead_agent",
        ) is True

        # Step 3: Prompt Injection triggers Untrusted Web Scraping Agent B to call stripe tool
        # Must be rejected because agent_id doesn't match!
        assert allowlist.check(
            user_id,
            "mcp_invoke",
            "mcp__stripe__charge_customer",
            agent_id="web_scraper_subagent",
        ) is False

        # Step 4: Multi-tenant / Anonymous caller attempt
        assert allowlist.check(
            user_id,
            "mcp_invoke",
            "mcp__stripe__charge_customer",
            agent_id=None,
        ) is False

    async def test_remove_by_agent_scope(self):
        allowlist = Allowlist()
        user_id = "sandbox"

        await allowlist.add(
            user_id,
            AllowlistEntry(
                permission="mcp_invoke",
                tool_name="mcp__aws__terminate_instance",
                agent_id="infra_agent",
            ),
        )
        await allowlist.add(
            user_id,
            AllowlistEntry(
                permission="mcp_invoke",
                tool_name="mcp__aws__terminate_instance",
                agent_id="qa_agent",
            ),
        )

        # Remove only infra_agent's allowlist entry
        await allowlist.remove(
            user_id,
            "mcp_invoke",
            tool_name="mcp__aws__terminate_instance",
            agent_id="infra_agent",
        )

        assert allowlist.check(
            user_id,
            "mcp_invoke",
            "mcp__aws__terminate_instance",
            agent_id="infra_agent",
        ) is False

        # qa_agent entry remains intact
        assert allowlist.check(
            user_id,
            "mcp_invoke",
            "mcp__aws__terminate_instance",
            agent_id="qa_agent",
        ) is True
