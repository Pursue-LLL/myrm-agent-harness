"""MCP hybrid routing — direct tool vs PTC skill path selection.

[INPUT]
- toolkits.mcp.connection_manager::get_mcp_connection_manager (POS: MCP connection pool)
- agent.skills.mcp.core_generator::mcp_skill_generator (POS: PTC skill metadata generator)

[OUTPUT]
- route_mcp_servers(): split MCP servers into direct tools vs PTC skills
- apply_aggregate_threshold(): cap aggregate direct-tool token budget, overflow → deferred
- PTC_OVERHEAD_MULTIPLIER, FALLBACK_PTC_BRIDGE_TOKENS, _compute_direct_threshold, _estimate_schema_tokens

[POS]
MCP schema-token routing for SkillAgent factory. Keeps hybrid direct/PTC decision isolated from assembly.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

    from myrm_agent_harness.agent.skills import SkillMetadata
    from myrm_agent_harness.toolkits.mcp.client import MCPServerConfigProtocol
    from myrm_agent_harness.toolkits.mcp.config import MCPConfig

logger = logging.getLogger(__name__)

PTC_OVERHEAD_MULTIPLIER = 2
"""Multiplier for PTC bridge tool schema cost.
If MCP schema > bridge_cost * multiplier, PTC is more efficient."""

FALLBACK_PTC_BRIDGE_TOKENS = 450
"""Estimated PTC bridge tool schema overhead (skill_select_tool + discover_capability_tool)
when actual bridge tools are not yet available for measurement."""

CHARS_PER_TOKEN = 4.0

AGGREGATE_DIRECT_TOKEN_BUDGET = 2700
"""Maximum total schema tokens for all MCP direct tools combined.

When multiple lightweight MCP servers individually pass the per-server threshold
but their aggregate schema exceeds this budget, the excess tools are deferred
(sorted by per-tool schema size descending — largest tools deferred first).

Value rationale: ~3x per-server threshold (900) accommodates 3-4 typical lightweight
servers without deferral, while preventing 10+ servers from bloating the prompt.
"""


def _compute_direct_threshold(bridge_tools: Sequence[BaseTool] | None = None) -> int:
    """Compute the schema token threshold for direct-vs-PTC routing."""
    if bridge_tools:
        bridge_tokens = _estimate_schema_tokens(bridge_tools)
    else:
        bridge_tokens = FALLBACK_PTC_BRIDGE_TOKENS
    return bridge_tokens * PTC_OVERHEAD_MULTIPLIER


def _estimate_schema_tokens(tools: Sequence[BaseTool]) -> int:
    """Estimate schema tokens for a list of tools via chars/4 rule."""
    total_chars = 0
    for tool in tools:
        try:
            schema = tool.get_input_schema().schema() if hasattr(tool, "get_input_schema") else {}
        except Exception:
            schema = {}
        entry = {"name": tool.name, "description": tool.description or "", "parameters": schema}
        total_chars += len(json.dumps(entry, ensure_ascii=False, separators=(",", ":")))
    return int(total_chars / CHARS_PER_TOKEN + 0.5)


def _estimate_single_tool_tokens(tool: BaseTool) -> int:
    """Estimate schema tokens for a single tool."""
    try:
        schema = tool.get_input_schema().schema() if hasattr(tool, "get_input_schema") else {}
    except Exception:
        schema = {}
    entry = {"name": tool.name, "description": tool.description or "", "parameters": schema}
    return int(len(json.dumps(entry, ensure_ascii=False, separators=(",", ":"))) / CHARS_PER_TOKEN + 0.5)


def apply_aggregate_threshold(
    mcp_direct_tools: list[BaseTool],
    budget: int = AGGREGATE_DIRECT_TOKEN_BUDGET,
) -> tuple[list[BaseTool], list[BaseTool]]:
    """Cap aggregate direct MCP tools within a token budget.

    When the combined schema of all direct MCP tools exceeds *budget*,
    the largest tools (by schema token cost) are moved to the deferred list
    until the remaining tools fit within budget.

    Returns:
        (kept_direct, overflow_deferred) — tools to bind directly and tools to defer.
    """
    total_tokens = _estimate_schema_tokens(mcp_direct_tools)
    if total_tokens <= budget:
        return mcp_direct_tools, []

    scored = [(t, _estimate_single_tool_tokens(t)) for t in mcp_direct_tools]
    scored.sort(key=lambda x: x[1], reverse=True)

    kept: list[BaseTool] = []
    deferred: list[BaseTool] = []
    running_tokens = 0

    remaining = list(reversed(scored))
    for t, tokens in remaining:
        if running_tokens + tokens <= budget:
            kept.append(t)
            running_tokens += tokens
        else:
            deferred.append(t)

    logger.info(
        "MCP aggregate threshold: %d tokens total > %d budget → kept %d tools (%d tokens), deferred %d tools",
        total_tokens,
        budget,
        len(kept),
        running_tokens,
        len(deferred),
    )
    return kept, deferred


def _config_to_dict(cfg: MCPServerConfigProtocol) -> dict[str, object]:
    """Convert MCPServerConfigProtocol to dict without model_dump."""
    return {
        "name": cfg.name,
        "type": cfg.type,
        "url": cfg.url,
        "command": cfg.command,
        "args": cfg.args,
        "description": cfg.description,
        "extra_params": cfg.extra_params,
    }


async def route_mcp_servers(
    mcp_servers: Sequence[MCPServerConfigProtocol],
) -> tuple[list[SkillMetadata], list[BaseTool]]:
    """Route MCP servers into direct-tool or PTC-skill paths based on schema token cost."""
    from myrm_agent_harness.toolkits.mcp.connection_manager import (
        get_mcp_connection_manager,
    )

    ptc_servers: list[MCPConfig] = []
    mcp_skills: list[SkillMetadata] = []
    mcp_direct_tools: list[BaseTool] = []
    direct_threshold = _compute_direct_threshold()

    all_mcp_configs = cast("list[MCPConfig]", list(mcp_servers))
    manager = await get_mcp_connection_manager()

    for cfg in all_mcp_configs:
        try:
            conn = await manager.get_connection([cfg])
        except Exception as e:
            logger.warning("MCP server '%s' failed to connect, skipping: %s", cfg.name, e)
            continue

        server_tools = conn.tools_by_server.get(cfg.name) or next(
            (tools for tools in conn.tools_by_server.values() if tools), []
        )
        if not server_tools:
            logger.warning("MCP server '%s' exposed no tools, skipping", cfg.name)
            continue

        schema_tokens = _estimate_schema_tokens(server_tools)
        if schema_tokens <= direct_threshold:
            mcp_direct_tools.extend(server_tools)
            logger.info(
                "MCP hybrid: server '%s' (%d tools, ~%d tokens, threshold=%d) → direct",
                cfg.name,
                len(server_tools),
                schema_tokens,
                direct_threshold,
            )
        else:
            ptc_servers.append(cfg)
            logger.info(
                "MCP hybrid: server '%s' (%d tools, ~%d tokens, threshold=%d) → PTC/Skill",
                cfg.name,
                len(server_tools),
                schema_tokens,
                direct_threshold,
            )

    if ptc_servers:
        from myrm_agent_harness.agent.skills.mcp.core_generator import (
            mcp_skill_generator,
        )
        from myrm_agent_harness.agent.skills.runtime.registry import skill_registry

        logger.info(
            "MCP PTC skill generation: %d server(s): %s",
            len(ptc_servers),
            [s.name for s in ptc_servers],
        )
        mcp_skills = await mcp_skill_generator.generate_metadata_only(ptc_servers)
        logger.info("MCP PTC skill generation: produced %d skill(s)", len(mcp_skills))

        for skill in mcp_skills:
            if skill.mcp:
                server_configs = [cfg for cfg in ptc_servers if cfg.name == skill.mcp.server]
                if server_configs:
                    skill.mcp.config = [_config_to_dict(cfg) for cfg in server_configs]
                else:
                    skill.mcp.config = [_config_to_dict(cfg) for cfg in ptc_servers]
            skill_registry.register(skill)

    logger.info(
        "MCP hybrid summary: %d direct tools, %d PTC skills",
        len(mcp_direct_tools),
        len(mcp_skills),
    )
    return mcp_skills, mcp_direct_tools
