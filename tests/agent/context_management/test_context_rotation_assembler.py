# ============================================================================
# Unit Tests for ContextRotationRuntimeAssembler (Item 155)
# Verifies three-tier runtime parameter rules, Fail-Loud assembly invariants,
# config-hashed MCP connection pooling (0-reconnect reuse), and rotation rebuild.
# ============================================================================

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.context_management.rotation import (
    ApprovalMode,
    ContextRotationRuntimeAssembler,
    McpServerConfig,
    RuntimeAssemblyError,
    ThinkingLevel,
)


def test_three_tier_assembly_structure() -> None:
    """Verifies that strict prefix, soft budget, and live security are assembled."""
    assembler = ContextRotationRuntimeAssembler()

    ctx = assembler.assemble_on_rotation(
        context_id="ctx-001",
        system_prompt="You are a principal engineer.",
        model_name="claude-3-7-sonnet",
        tool_signatures=("bash(cmd: str)", "read_file(path: str)"),
        thinking_level=ThinkingLevel.HIGH,
        mcp_configs=[],
        approval_mode=ApprovalMode.ASK_FIRST,
        allowed_tool_names=frozenset({"bash", "read_file"}),
    )

    assert ctx.context_id == "ctx-001"
    # Strict tier: frozen prefix
    assert ctx.strict_prefix.system_prompt == "You are a principal engineer."
    assert ctx.strict_prefix.model_name == "claude-3-7-sonnet"
    assert len(ctx.strict_prefix.prefix_hash) == 64  # Valid SHA-256

    # Soft tier: thinking budget
    assert ctx.soft_budget.thinking_level == ThinkingLevel.HIGH
    assert not ctx.soft_budget.suggest_compaction_before_shift

    # Live tier: dynamic permissions
    assert ctx.live_security.approval_mode == ApprovalMode.ASK_FIRST
    assert "bash" in ctx.live_security.allowed_tool_names


def test_fail_loud_assembly_invariant() -> None:
    """Verifies that corrupted configuration fails loudly without silent fallbacks."""
    assembler = ContextRotationRuntimeAssembler()

    # Empty prompt fails loud
    with pytest.raises(RuntimeAssemblyError, match="system_prompt cannot be blank"):
        assembler.assemble_on_rotation(
            context_id="ctx-err",
            system_prompt="",
            model_name="gpt-4o",
            tool_signatures=(),
            thinking_level=ThinkingLevel.LOW,
            mcp_configs=[],
        )

    # Duplicate MCP server IDs fail loud
    dup_configs = [
        McpServerConfig(server_id="mcp-srv", command_or_url="http://localhost:8001"),
        McpServerConfig(server_id="mcp-srv", command_or_url="http://localhost:8002"),
    ]
    with pytest.raises(RuntimeAssemblyError, match="Duplicate MCP server ID"):
        assembler.assemble_on_rotation(
            context_id="ctx-dup",
            system_prompt="valid prompt",
            model_name="gpt-4o",
            tool_signatures=(),
            thinking_level=ThinkingLevel.LOW,
            mcp_configs=dup_configs,
        )


def test_config_hashed_mcp_persistent_connection_reuse() -> None:
    """Verifies that unchanged MCP server configs achieve 0-reconnect reuse across rotations."""
    assembler = ContextRotationRuntimeAssembler()

    mcp_git = McpServerConfig(
        server_id="mcp-github",
        command_or_url="npx -y @modelcontextprotocol/server-github",
        env_vars=(("GITHUB_TOKEN", "ghp_mock"),),
        tools_whitelist=("create_issue", "get_pr"),
    )
    mcp_slack = McpServerConfig(
        server_id="mcp-slack",
        command_or_url="npx -y @modelcontextprotocol/server-slack",
        env_vars=(("SLACK_BOT_TOKEN", "xoxb_mock"),),
        tools_whitelist=("send_message",),
    )

    # Rotation 1 (Initial setup): both servers must connect
    ctx1 = assembler.assemble_on_rotation(
        context_id="rot-1",
        system_prompt="Prompt 1",
        model_name="deepseek-v3",
        tool_signatures=(),
        thinking_level=ThinkingLevel.MEDIUM,
        mcp_configs=[mcp_git, mcp_slack],
    )
    assert set(ctx1.mcp_pool_status.reconnected_servers) == {"mcp-github", "mcp-slack"}
    assert len(ctx1.mcp_pool_status.reused_servers) == 0
    assert assembler.get_mcp_reconnection_count("mcp-github") == 1
    assert assembler.get_mcp_reconnection_count("mcp-slack") == 1

    # Rotation 2 (Compaction event): configs unchanged -> 0 reconnects!
    ctx2 = assembler.assemble_on_rotation(
        context_id="rot-2",
        system_prompt="Prompt 1 (post-compaction)",
        model_name="deepseek-v3",
        tool_signatures=(),
        thinking_level=ThinkingLevel.MEDIUM,
        mcp_configs=[mcp_git, mcp_slack],
    )
    assert set(ctx2.mcp_pool_status.reused_servers) == {"mcp-github", "mcp-slack"}
    assert len(ctx2.mcp_pool_status.reconnected_servers) == 0
    # Reconnection count MUST remain 1 (zero respawns)
    assert assembler.get_mcp_reconnection_count("mcp-github") == 1
    assert assembler.get_mcp_reconnection_count("mcp-slack") == 1

    # Rotation 3: mcp-github modified, mcp-slack kept identical
    mcp_git_modified = McpServerConfig(
        server_id="mcp-github",
        command_or_url="npx -y @modelcontextprotocol/server-github",
        env_vars=(("GITHUB_TOKEN", "ghp_NEW_TOKEN"),),  # Changed config
        tools_whitelist=("create_issue", "get_pr", "list_repos"),
    )
    ctx3 = assembler.assemble_on_rotation(
        context_id="rot-3",
        system_prompt="Prompt 1 (post-compaction 2)",
        model_name="deepseek-v3",
        tool_signatures=(),
        thinking_level=ThinkingLevel.MEDIUM,
        mcp_configs=[mcp_git_modified, mcp_slack],
    )
    assert "mcp-slack" in ctx3.mcp_pool_status.reused_servers
    assert "mcp-github" in ctx3.mcp_pool_status.reconnected_servers
    assert assembler.get_mcp_reconnection_count("mcp-slack") == 1  # 0 reconnects
    assert assembler.get_mcp_reconnection_count("mcp-github") == 2  # Reconnected once


def test_mid_turn_prompt_update_and_rotation_rebuild() -> None:
    """Verifies that updating agent prompt rebuilds strict prefix on rotation."""
    assembler = ContextRotationRuntimeAssembler()

    ctx1 = assembler.assemble_on_rotation(
        context_id="turn-1",
        system_prompt="Initial Base Prompt",
        model_name="claude-3-7-sonnet",
        tool_signatures=(),
        thinking_level=ThinkingLevel.LOW,
        mcp_configs=[],
    )
    hash1 = ctx1.strict_prefix.prefix_hash

    # User modifies prompt mid-flight and triggers compaction rotation
    ctx2 = assembler.assemble_on_rotation(
        context_id="turn-2-post-rotation",
        system_prompt="Updated Specialized Architect Prompt",
        model_name="claude-3-7-sonnet",
        tool_signatures=(),
        thinking_level=ThinkingLevel.LOW,
        mcp_configs=[],
    )
    hash2 = ctx2.strict_prefix.prefix_hash

    assert ctx2.strict_prefix.system_prompt == "Updated Specialized Architect Prompt"
    assert hash1 != hash2  # Correctly recalculated prefix hash for cache alignment


def test_soft_thinking_budget_shift_warning() -> None:
    """Verifies that mid-turn reasoning level shift raises a cache disruption warning."""
    assembler = ContextRotationRuntimeAssembler()

    assembler.assemble_on_rotation(
        context_id="turn-1",
        system_prompt="Base Prompt",
        model_name="claude-3-7-sonnet",
        tool_signatures=(),
        thinking_level=ThinkingLevel.LOW,
        mcp_configs=[],
        is_context_rotation=True,
    )

    # Shift thinking level without compaction rotation
    ctx_mid = assembler.assemble_on_rotation(
        context_id="turn-2-mid-shift",
        system_prompt="Base Prompt",
        model_name="claude-3-7-sonnet",
        tool_signatures=(),
        thinking_level=ThinkingLevel.HIGH,
        mcp_configs=[],
        is_context_rotation=False,
    )

    assert ctx_mid.soft_budget.suggest_compaction_before_shift
    assert "Thinking level shifted" in ctx_mid.soft_budget.warning_note


def test_assembly_dataclass_serialization() -> None:
    """Verifies clean dictionary serialization for telemetry and persistence."""
    cfg = McpServerConfig(
        server_id="mcp-test",
        command_or_url="http://localhost:8000",
        env_vars=(("K", "V"),),
    )
    d = cfg.to_dict()
    assert d["server_id"] == "mcp-test"
    assert len(str(d["config_hash"])) == 64
