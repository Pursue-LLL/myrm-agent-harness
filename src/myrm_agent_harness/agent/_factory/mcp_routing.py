"""MCP hybrid routing — direct tool vs PTC skill path selection.

[INPUT]
- toolkits.mcp.connection_manager::get_mcp_connection_manager (POS: MCP connection pool)
- agent.skills.mcp.core_generator::mcp_skill_generator (POS: PTC skill metadata generator)

[OUTPUT]
- route_mcp_servers(): split MCP servers into direct tools vs PTC skills
- demote_direct_servers_over_budget(): whole-server Skill demotion when aggregate direct budget exceeded
- PTC_OVERHEAD_MULTIPLIER, FALLBACK_PTC_OVERHEAD_TOKENS, compute_direct_threshold, estimate_schema_tokens

[POS]
MCP schema-token routing for SkillAgent factory. **Two outcomes only** (see
``TOOL_DESIGN_STRATEGY.md`` §MCP 路由铁律 — 禁止 catalog_invoke / proxy 第三路径):
- Direct FC (AUTO): per-server and aggregate within budget → native Turn1 FC with full schema
- Direct FC (DIRECT_FC mode): forced direct regardless of per-server / aggregate thresholds
- MCP PTC: per-server schema over threshold OR aggregate overflow → skill_select + bash SOP
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from myrm_agent_harness.agent._factory.mcp_surface import (
    MCPSurfaceMode,
    parse_mcp_surface_mode,
)
from myrm_agent_harness.toolkits.mcp.config import (
    MCPConfig,
    mcp_config_to_runtime_dict,
)

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

    from myrm_agent_harness.agent.skills import SkillMetadata
    from myrm_agent_harness.toolkits.mcp.client import MCPServerConfigProtocol

logger = logging.getLogger(__name__)

PTC_OVERHEAD_MULTIPLIER = 25
"""Per-server schema threshold = PTC_overhead_tokens × multiplier.

Empirical derivation (12306 benchmark, 8 tools, 2077 schema tokens):
  PTC extra cost ≈ ΔT×P + D_eff×(T+ΔT−2) where ΔT=3, P≈11K, D_eff≈17.5K, T≈5
  → theoretical crossover ≈ 27.8K tokens (≈100+ tools)
  → practical threshold = crossover × 0.4 safety margin ≈ 11K tokens
  → multiplier = 11K / 450 ≈ 25

Below this threshold DIRECT_FC always wins because PTC's 3 extra turns
(skill_select + file_read + planning) cause quadratic history accumulation
that far exceeds the per-turn schema injection cost of DIRECT_FC."""

FALLBACK_PTC_OVERHEAD_TOKENS = 450
"""Estimated PTC overhead (skill_select_tool + skill_search_tool schema tokens)
when actual overhead tools are not available for measurement."""

CHARS_PER_TOKEN = 4.0

AGGREGATE_DIRECT_TOKEN_BUDGET = 15_000
"""Maximum aggregate schema tokens for all MCP direct servers combined.

Set to ~1.5× the per-server threshold (450×25 = 11.25K) so that 2–3 medium
MCP servers (each ≈5K tokens) can coexist as DIRECT without demotion.
Demoting multiple servers to PTC multiplies the SOP/L3 accumulation penalty
(each PTC server adds its own 3-turn overhead), so the aggregate cap should
be generous.

When exceeded, whole servers (largest first) are demoted to PTC/Skill."""


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
    """Return the tool's JSON Schema, falling back for malformed tools.

    MCP tools carry a native JSON Schema ``dict`` as ``args_schema`` (see
    ``tool_converter``); for those the dict is returned verbatim so schema
    token estimates reflect the exact schema the LLM receives. Built-in
    tools keep Pydantic models and are serialized via ``model_json_schema``.
    """
    try:
        args_schema = getattr(tool, "args_schema", None)
        if isinstance(args_schema, dict):
            return cast("dict[str, object]", args_schema)
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
        total += get_token_count(json.dumps(entry, ensure_ascii=False, separators=(",", ":")))
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
            server_configs = [cfg for cfg in ptc_servers if cfg.name == skill.mcp.server]
            if server_configs:
                skill.mcp.config = [_config_to_dict(cfg) for cfg in server_configs]
            else:
                skill.mcp.config = [_config_to_dict(cfg) for cfg in ptc_servers]
        skill_registry.register(skill)
    return mcp_skills


def _config_to_dict(cfg: MCPServerConfigProtocol) -> dict[str, object]:
    """Convert MCPServerConfigProtocol to runtime dict preserving all fields."""
    return mcp_config_to_runtime_dict(cfg)


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
        else parse_mcp_surface_mode(str(surface_mode) if surface_mode is not None else None)
    )
    from myrm_agent_harness.toolkits.mcp.connection_manager import (
        get_mcp_connection_manager,
    )

    ptc_servers: list[MCPConfig] = []
    direct_bundles: list[_DirectServerBundle] = []
    direct_threshold = compute_direct_threshold()

    all_mcp_configs = cast("list[MCPConfig]", list(mcp_servers))
    manager = await get_mcp_connection_manager()
    force_direct = resolved_surface == MCPSurfaceMode.DIRECT_FC

    conn_results = await asyncio.gather(
        *(manager.get_connection([cfg]) for cfg in all_mcp_configs),
        return_exceptions=True,
    )

    from myrm_agent_harness.toolkits.mcp.mcp_schema_cache import (
        load_cached_schema,
        save_cached_schema,
    )

    for cfg, conn in zip(all_mcp_configs, conn_results, strict=True):
        cfg_hash = manager._make_config_hash([cfg])
        if isinstance(conn, BaseException):
            cached = load_cached_schema(cfg_hash)
            if cached is not None and cached.tools:
                logger.info(
                    "MCP server '%s' offline/unconnected; cached schema available (%d tools, ~%d tokens)",
                    cfg.name,
                    len(cached.tools),
                    cached.total_schema_tokens,
                )
            logger.warning("MCP server '%s' failed to connect, skipping: %s", cfg.name, conn)
            continue

        server_tools = conn.tools_by_server.get(cfg.name) or next(
            (tools for tools in conn.tools_by_server.values() if tools), []
        )
        if not server_tools:
            logger.warning("MCP server '%s' exposed no tools, skipping", cfg.name)
            continue

        save_cached_schema(cfg_hash, cfg.name, server_tools)

        schema_tokens = estimate_schema_tokens(server_tools)
        if schema_tokens <= direct_threshold or force_direct:
            direct_bundles.append(
                _DirectServerBundle(
                    config=cfg,
                    tools=tuple(server_tools),
                    schema_tokens=schema_tokens,
                )
            )
            if force_direct and schema_tokens > direct_threshold:
                logger.info(
                    "MCP direct_fc override: server '%s' (%d tools, ~%d tokens, threshold=%d) → forced direct",
                    cfg.name,
                    len(server_tools),
                    schema_tokens,
                    direct_threshold,
                )
            else:
                logger.info(
                    "MCP hybrid: server '%s' (%d tools, ~%d tokens, threshold=%d) → direct candidate",
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

    if resolved_surface == MCPSurfaceMode.DIRECT_FC:
        kept_bundles = direct_bundles
        logger.info(
            "MCP direct_fc override: skipping aggregate demotion (%d direct candidate bundles)",
            len(kept_bundles),
        )
    else:
        kept_bundles, demoted_configs = demote_direct_servers_over_budget(direct_bundles)
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
