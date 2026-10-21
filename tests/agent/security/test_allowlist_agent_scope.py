"""Allowlist agent-scope isolation: a hosted MCP approval granted to one agent must not authorize another."""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.security.approval_flow import Allowlist, AllowlistEntry


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
        assert (
            allowlist.check(
                user_id,
                "mcp_invoke",
                "mcp__stripe__charge_customer",
                agent_id="finance_lead_agent",
            )
            is True
        )

        # Step 3: Prompt Injection triggers Untrusted Web Scraping Agent B to call stripe tool
        # Must be rejected because agent_id doesn't match!
        assert (
            allowlist.check(
                user_id,
                "mcp_invoke",
                "mcp__stripe__charge_customer",
                agent_id="web_scraper_subagent",
            )
            is False
        )

        # Step 4: Multi-tenant / Anonymous caller attempt
        assert (
            allowlist.check(
                user_id,
                "mcp_invoke",
                "mcp__stripe__charge_customer",
                agent_id=None,
            )
            is False
        )

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

        assert (
            allowlist.check(
                user_id,
                "mcp_invoke",
                "mcp__aws__terminate_instance",
                agent_id="infra_agent",
            )
            is False
        )

        # qa_agent entry remains intact
        assert (
            allowlist.check(
                user_id,
                "mcp_invoke",
                "mcp__aws__terminate_instance",
                agent_id="qa_agent",
            )
            is True
        )
