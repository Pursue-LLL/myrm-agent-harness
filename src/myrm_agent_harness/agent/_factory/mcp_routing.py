"""MCP hybrid routing — direct tool vs PTC skill path selection.

[INPUT]
- toolkits.mcp.connection_manager::get_mcp_connection_manager (POS: MCP connection pool)
- agent.skills.mcp.core_generator::mcp_skill_generator (POS: PTC skill metadata generator)

[OUTPUT]
- route_mcp_servers(): split MCP servers into direct tools vs PTC skills
- demote_direct_servers_over_budget(): whole-server Skill demotion when aggregate direct budget exceeded
- PTC_OVERHEAD_MULTIPLIER, FALLBACK_PTC_OVERHEAD_TOKENS, compute_direct_threshold, estimate_schema_tokens
- _compact_description/_compress_direct_tools: direct MCP tool description compaction for token-noise control

[POS]
MCP schema-token routing for SkillAgent factory. **Two outcomes only** (see
``TOOL_DESIGN_STRATEGY.md`` §MCP 路由铁律 — 禁止 catalog_invoke / proxy 第三路径):
- Direct FC: per-server and aggregate within budget → native Turn1 FC with full schema
- MCP PTC: per-server schema over threshold OR aggregate overflow → skill_select + bash SOP
"""

from __future__ import annotations

import copy
import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from myrm_agent_harness.agent._factory.mcp_surface import (
    MCPSurfaceMode,
    parse_mcp_surface_mode,
)
from myrm_agent_harness.toolkits.mcp.config import MCPConfig

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

    from myrm_agent_harness.agent.skills import SkillMetadata
    from myrm_agent_harness.toolkits.mcp.client import MCPServerConfigProtocol

logger = logging.getLogger(__name__)

PTC_OVERHEAD_MULTIPLIER = 2
"""Multiplier for PTC overhead tool schema cost (skill_search + skill_select).
If MCP schema > overhead * multiplier, PTC/Skill is more efficient."""

FALLBACK_PTC_OVERHEAD_TOKENS = 450
"""Estimated PTC overhead (skill_select_tool + skill_search_tool schema tokens)
when actual overhead tools are not available for measurement."""

CHARS_PER_TOKEN = 4.0

AGGREGATE_DIRECT_TOKEN_BUDGET = 1200
"""Maximum total schema tokens for all MCP direct tools combined.

When multiple lightweight MCP servers individually pass the per-server threshold
but their aggregate schema exceeds this budget, whole servers (largest first) are
demoted to PTC/Skill until the remaining direct pool fits within budget.

Single aggregate threshold — overflow demotes whole servers to PTC/Skill (largest first).
"""

DIRECT_MCP_DESCRIPTION_SOFT_LIMIT = 180
"""Soft character limit for direct MCP tool descriptions.

Direct tools remain callable with full parameter schema. This limit trims verbose
natural-language prose in descriptions to reduce EXTENDED Turn1 token noise.
"""


@dataclass(frozen=True, slots=True)
class _DirectServerBundle:
    config: MCPConfig
    tools: tuple[BaseTool, ...]
    schema_tokens: int


def demote_direct_servers_over_budget(
    bundles: list[_DirectServerBundle],
    budget: int = AGGREGATE_DIRECT_TOKEN_BUDGET,
) -> tuple[list[_DirectServerBundle], list[MCPConfig]]:
    """Demote largest direct MCP servers to Skill until aggregate schema fits budget."""
    if not bundles:
        return [], []

    remaining = list(bundles)
    demoted: list[MCPConfig] = []

    def _total_tokens(items: list[_DirectServerBundle]) -> int:
        return sum(b.schema_tokens for b in items)

    while remaining and _total_tokens(remaining) > budget:
        largest = max(remaining, key=lambda b: b.schema_tokens)
        remaining.remove(largest)
        demoted.append(largest.config)
        logger.info(
            "MCP aggregate demotion: server '%s' (~%d tokens) → PTC/Skill",
            largest.config.name,
            largest.schema_tokens,
        )

    return remaining, demoted


def compute_direct_threshold(
    ptc_overhead_tools: Sequence[BaseTool] | None = None,
) -> int:
    """Compute the schema token threshold for direct-vs-PTC routing."""
    if ptc_overhead_tools:
        overhead_tokens = estimate_schema_tokens(ptc_overhead_tools)
    else:
        overhead_tokens = FALLBACK_PTC_OVERHEAD_TOKENS
    return overhead_tokens * PTC_OVERHEAD_MULTIPLIER


def _input_schema(tool: BaseTool) -> dict[str, object]:
    """Return a Pydantic v2 JSON schema, falling back for malformed tools."""
    try:
        schema_model = tool.get_input_schema()
        return cast("dict[str, object]", schema_model.model_json_schema())
    except Exception:
        return {}


def estimate_schema_tokens(tools: Sequence[BaseTool]) -> int:
    """Estimate schema tokens for a list of tools via planning SSOT tiktoken."""
    from myrm_agent_harness.utils.text_utils import get_token_count

    total = 0
    for tool in tools:
        schema = _input_schema(tool)
        entry = {
            "name": tool.name,
            "description": tool.description or "",
            "parameters": schema,
        }
        total += get_token_count(
            json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
        )
    return total


def estimate_single_tool_tokens(tool: BaseTool) -> int:
    """Estimate schema tokens for a single tool."""
    from myrm_agent_harness.utils.text_utils import get_token_count

    schema = _input_schema(tool)
    entry = {
        "name": tool.name,
        "description": tool.description or "",
        "parameters": schema,
    }
    return get_token_count(json.dumps(entry, ensure_ascii=False, separators=(",", ":")))


def _compact_description(
    description: str, limit: int = DIRECT_MCP_DESCRIPTION_SOFT_LIMIT
) -> str:
    """Compact verbose MCP tool descriptions while preserving a clear summary."""
    normalized = " ".join(description.split())
    if len(normalized) <= limit:
        return normalized
    summary = normalized[:limit].rstrip(" ,.;:")
    return f"{summary}."


def _compress_direct_tools(tools: Sequence[BaseTool]) -> list[BaseTool]:
    """Return direct MCP tools with compacted descriptions for token budget control."""
    compressed: list[BaseTool] = []
    for tool in tools:
        compacted = _compact_description(tool.description or "")
        if compacted == (tool.description or ""):
            compressed.append(tool)
            continue

        cloned: BaseTool | None = None
        model_copy = getattr(tool, "model_copy", None)
        if callable(model_copy):
            try:
                cloned = cast("BaseTool", model_copy(update={"description": compacted}))
                if getattr(cloned, "name", None) != tool.name:
                    cloned = None
            except Exception:
                cloned = None
        if cloned is not None:
            compressed.append(cloned)
            continue

        try:
            fallback_copy = copy.copy(tool)
            fallback_copy.description = compacted
            compressed.append(cast("BaseTool", fallback_copy))
        except Exception:
            logger.debug("Failed to compact MCP tool description for %s", tool.name)
            compressed.append(tool)
    return compressed


async def _generate_mcp_skills(
    ptc_servers: list[MCPConfig],
) -> list[SkillMetadata]:
    from myrm_agent_harness.agent.skills.mcp.core_generator import mcp_skill_generator
    from myrm_agent_harness.agent.skills.runtime.registry import skill_registry

    if not ptc_servers:
        return []

    logger.info(
        "MCP PTC skill generation: %d server(s): %s",
        len(ptc_servers),
        [s.name for s in ptc_servers],
    )
    mcp_skills = await mcp_skill_generator.generate_metadata_only(ptc_servers)
    logger.info("MCP PTC skill generation: produced %d skill(s)", len(mcp_skills))

    for skill in mcp_skills:
        if skill.mcp:
            server_configs = [
                cfg for cfg in ptc_servers if cfg.name == skill.mcp.server
            ]
            if server_configs:
                skill.mcp.config = [_config_to_dict(cfg) for cfg in server_configs]
            else:
                skill.mcp.config = [_config_to_dict(cfg) for cfg in ptc_servers]
        skill_registry.register(skill)
    return mcp_skills


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
        "host_serial": getattr(cfg, "host_serial", False),
        "keepalive_interval": getattr(cfg, "keepalive_interval", None),
    }


@dataclass(frozen=True, slots=True)
class MCPRoutingResult:
    """Result of MCP hybrid routing (direct Turn1 FC or MCP PTC only)."""

    skills: list[SkillMetadata]
    direct_tools: list[BaseTool]


async def route_mcp_servers(
    mcp_servers: Sequence[MCPServerConfigProtocol],
    *,
    surface_mode: MCPSurfaceMode | str | None = MCPSurfaceMode.AUTO,
) -> MCPRoutingResult:
    """Route MCP servers into direct Turn1 tools or MCP PTC paths."""
    resolved_surface = (
        surface_mode
        if isinstance(surface_mode, MCPSurfaceMode)
        else parse_mcp_surface_mode(
            str(surface_mode) if surface_mode is not None else None
        )
    )
    from myrm_agent_harness.agent.skills.runtime.registry import skill_registry
    from myrm_agent_harness.toolkits.mcp.connection_manager import (
        get_mcp_connection_manager,
    )

    skill_registry.clear_mcp_skills()

    ptc_servers: list[MCPConfig] = []
    direct_bundles: list[_DirectServerBundle] = []
    direct_threshold = compute_direct_threshold()

    all_mcp_configs = cast("list[MCPConfig]", list(mcp_servers))
    manager = await get_mcp_connection_manager()

    for cfg in all_mcp_configs:
        try:
            conn = await manager.get_connection([cfg])
        except Exception as e:
            logger.warning(
                "MCP server '%s' failed to connect, skipping: %s", cfg.name, e
            )
            continue

        server_tools = conn.tools_by_server.get(cfg.name) or next(
            (tools for tools in conn.tools_by_server.values() if tools), []
        )
        if not server_tools:
            logger.warning("MCP server '%s' exposed no tools, skipping", cfg.name)
            continue

        raw_schema_tokens = estimate_schema_tokens(server_tools)
        if raw_schema_tokens <= direct_threshold:
            compressed_tools = tuple(_compress_direct_tools(server_tools))
            schema_tokens = estimate_schema_tokens(compressed_tools)
            direct_bundles.append(
                _DirectServerBundle(
                    config=cfg,
                    tools=compressed_tools,
                    schema_tokens=schema_tokens,
                )
            )
            logger.info(
                "MCP hybrid: server '%s' (%d tools, raw~%d tokens, compact~%d tokens, threshold=%d) → direct candidate",
                cfg.name,
                len(server_tools),
                raw_schema_tokens,
                schema_tokens,
                direct_threshold,
            )
        else:
            ptc_servers.append(cfg)
            logger.info(
                "MCP hybrid: server '%s' (%d tools, ~%d tokens, threshold=%d) → PTC/Skill",
                cfg.name,
                len(server_tools),
                raw_schema_tokens,
                direct_threshold,
            )

    if resolved_surface == MCPSurfaceMode.DIRECT_FC:
        kept_bundles = direct_bundles
        logger.info(
            "MCP direct_fc override: skipping aggregate demotion (%d direct candidate bundles)",
            len(kept_bundles),
        )
    else:
        kept_bundles, demoted_configs = demote_direct_servers_over_budget(
            direct_bundles
        )
        ptc_servers.extend(demoted_configs)

    mcp_direct_tools: list[BaseTool] = []
    for bundle in kept_bundles:
        mcp_direct_tools.extend(bundle.tools)

    mcp_skills = await _generate_mcp_skills(ptc_servers)

    logger.info(
        "MCP routing summary: %d direct tools, %d PTC skills",
        len(mcp_direct_tools),
        len(mcp_skills),
    )
    return MCPRoutingResult(
        skills=mcp_skills,
        direct_tools=mcp_direct_tools,
    )
