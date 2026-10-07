"""Unit tests for Cold Start Context Profiler and On-Demand MCP Mount Suite.

Verifies baseline context token breakdown across system prompt, core tools, and MCP servers,
session-level MCP hibernation, JIT prompt intent re-activation, and token savings metrics.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.context_management import (
    ColdStartContextProfile,
    ColdStartContextProfilerAndOnDemandMcpMountSuite,
    ColdStartContextProfilerEngine,
    ContextComponentKind,
    McpMountMutationResult,
    McpServerDescriptor,
    McpServerMountState,
    OnDemandMcpMountManager,
)


def test_cold_start_profiler_engine_breakdown() -> None:
    """Verify transparent cold start token profiling across system prompt, tools, and MCP."""
    engine = ColdStartContextProfilerEngine(
        mcp_warning_token_threshold=4000,
        mcp_warning_ratio_threshold=0.35,
    )

    system_prompt = "You are an expert AI engineer with deep knowledge in systems programming." * 10
    core_tools = [
        {"name": "bash", "description": "Execute shell command in sandbox."},
        {"name": "view_file", "description": "Read file contents from workspace."},
    ]
    mcp_servers = [
        McpServerDescriptor(
            server_id="github",
            display_name="GitHub MCP",
            tool_names=["create_pr", "list_issues"],
            estimated_schema_tokens=1500,
            mount_state=McpServerMountState.MOUNTED_ACTIVE,
            tags=["vcs", "code"],
        ),
        McpServerDescriptor(
            server_id="jira",
            display_name="Atlassian Jira MCP",
            tool_names=["create_ticket", "get_sprint", "update_status"],
            estimated_schema_tokens=3200,
            mount_state=McpServerMountState.MOUNTED_ACTIVE,
            tags=["collaboration", "crm", "remote"],
        ),
        McpServerDescriptor(
            server_id="figma",
            display_name="Figma Design MCP",
            tool_names=["inspect_node", "get_file_styles"],
            estimated_schema_tokens=2800,
            mount_state=McpServerMountState.MOUNTED_ACTIVE,
            tags=["design", "ui"],
        ),
    ]
    instruction_memory = "# Project Conventions\nAlways follow PEP 8 and use strong types."

    profile = engine.profile_cold_start(
        session_id="sess-init-01",
        system_prompt=system_prompt,
        core_tools=core_tools,
        mcp_servers=mcp_servers,
        instruction_memory=instruction_memory,
    )

    assert profile.total_estimated_tokens > 7000
    # MCP total is 1500 + 3200 + 2800 = 7500 tokens
    assert profile.mcp_tokens_ratio > 0.50
    # Diagnostic warning must trigger due to >35% ratio
    assert len(profile.warnings) > 0
    # Heuristics must suggest sleeping Jira and Figma for local tasks
    assert "jira" in profile.suggested_mcp_sleep
    assert "figma" in profile.suggested_mcp_sleep

    # Visual tree rendering verification
    rendered_tree = engine.render_profile_tree(profile)
    assert "Cold-Start Context Profile" in rendered_tree
    assert "Core Built-in Tools" in rendered_tree
    assert "External MCP Tools" in rendered_tree
    assert "Suggested MCP sleep" in rendered_tree


def test_on_demand_mcp_mount_manager_hibernation_and_jit() -> None:
    """Verify session-level MCP hibernation and Just-In-Time prompt intent activation."""
    servers = [
        McpServerDescriptor(
            server_id="jira",
            display_name="Jira MCP",
            tool_names=["jira_create_issue", "jira_search"],
            estimated_schema_tokens=3000,
            mount_state=McpServerMountState.MOUNTED_ACTIVE,
        ),
        McpServerDescriptor(
            server_id="slack",
            display_name="Slack MCP",
            tool_names=["slack_post_message"],
            estimated_schema_tokens=1800,
            mount_state=McpServerMountState.MOUNTED_ACTIVE,
        ),
    ]
    manager = OnDemandMcpMountManager(initial_servers=servers)
    assert manager.get_active_tokens() == 4800

    # 1. Hibernate Jira
    mut1 = manager.hibernate_server("jira")
    assert mut1.new_state == McpServerMountState.SLEEPING
    assert mut1.tokens_delta == -3000
    assert manager.get_active_tokens() == 1800

    # 2. Hibernate Slack
    mut2 = manager.hibernate_server("slack")
    assert mut2.new_state == McpServerMountState.SLEEPING
    assert mut2.tokens_delta == -1800
    assert manager.get_active_tokens() == 0

    # 3. Unrelated prompt must not re-activate
    no_activations = manager.jit_activate_by_prompt("Refactor database query in repo.")
    assert len(no_activations) == 0
    assert manager.get_active_tokens() == 0

    # 4. Prompt with @jira mention triggers JIT activation
    activations = manager.jit_activate_by_prompt("Can you update the ticket via @jira?")
    assert len(activations) == 1
    assert activations[0].server_id == "jira"
    assert activations[0].new_state == McpServerMountState.MOUNTED_ACTIVE
    assert activations[0].tokens_delta == 3000
    assert manager.get_active_tokens() == 3000


def test_cold_start_profiler_suite_facade_and_token_savings() -> None:
    """Verify master suite facade coordination, token reduction ratio, and lifecycle."""
    jira_desc = McpServerDescriptor(
        server_id="jira",
        display_name="Jira MCP",
        tool_names=["jira_issue"],
        estimated_schema_tokens=4000,
    )
    figma_desc = McpServerDescriptor(
        server_id="figma",
        display_name="Figma MCP",
        tool_names=["figma_node"],
        estimated_schema_tokens=3500,
    )
    suite = ColdStartContextProfilerAndOnDemandMcpMountSuite(initial_servers=[jira_desc, figma_desc])

    # 1. Baseline profile
    p1 = suite.profile_session("sess-test", system_prompt="System Prompt Test")
    assert p1.total_estimated_tokens >= 7500

    # 2. Hibernate both external servers
    suite.hibernate_server("jira")
    suite.hibernate_server("figma")

    # 3. Profile after hibernation: MCP tokens should be 0
    p2 = suite.profile_session("sess-test", system_prompt="System Prompt Test")
    mcp_comp = next(c for c in p2.components if c.kind == ContextComponentKind.MCP_EXTERNAL_TOOLS)
    assert mcp_comp.estimated_tokens == 0

    # 4. Inspect savings metrics
    metrics = suite.get_token_savings_metrics()
    assert metrics["currently_sleeping_mcp_servers"] == 2
    assert metrics["suppressed_mcp_tokens"] == 7500
    assert metrics["mcp_tokens_reduction_ratio"] == 1.0

    # 5. Preflight scan activates Jira on mention
    acts = suite.preflight_scan_prompt("Sync bug details with @jira please.")
    assert len(acts) == 1
    assert acts[0].server_id == "jira"

    # 6. Render Markdown tree
    md = suite.render_context_breakdown_markdown("sess-test", system_prompt="System Prompt")
    assert "Cold-Start Context Profile" in md
