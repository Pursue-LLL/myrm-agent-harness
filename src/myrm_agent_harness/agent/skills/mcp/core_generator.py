"""MCP Skill Generator - MCP-to-Skill conversion with progressive disclosure.

Implements:
- Level 1: generate_metadata_only() — lightweight SkillMetadata (startup)
- Level 2: generate_skill_content() — SKILL.md content (on-demand)
- Level 3: generate_tool_doc() — single tool documentation (on-demand)

[INPUT]
- backends.skills.types::MCPSkillData, (POS: Provides ArtifactInfo, infer_language, infer_artifact_type.)
- toolkits.mcp::MCPAgent, (POS: MCP toolkit entry point. Aggregates client management, agent tool fetching, connection pooling, configuration, and security validation for unified MCP protocol support.)

[OUTPUT]
- MCPSkillGenerator: MCP service to skill generator with progressive disclosure.

[POS]
MCP Skill Generator - MCP-to-Skill conversion with progressive disclosure.
"""

from __future__ import annotations

import asyncio
import logging
import re

from langchain_core.tools import BaseTool

from myrm_agent_harness.agent.skills.mcp.description import resolve_description
from myrm_agent_harness.agent.skills.mcp.doc_rendering import (
    INSTRUCTIONS_TOKEN_LIMIT,
    L2_MAX_TOKENS,
    build_tool_section,
    cap_instructions,
    text_field,
    tool_section_budget,
)
from myrm_agent_harness.agent.skills.mcp.schema_doc_utils import (
    TOOL_DOC_TEMPLATE,
    build_call_example,
    build_params_section,
    normalize_input_schema,
)
from myrm_agent_harness.agent.skills.mcp.tool_name_utils import (
    build_tool_name_map,
    resolve_mcp_tool_name,
)
from myrm_agent_harness.backends.skills.types import MCPSkillData, SkillMetadata
from myrm_agent_harness.toolkits.mcp import MCPConfig
from myrm_agent_harness.toolkits.mcp.config import mcp_config_to_runtime_dict
from myrm_agent_harness.utils.text_utils import get_token_count

logger = logging.getLogger(__name__)

type JsonDict = dict[str, object]


SKILL_USAGE_TEMPLATE = """
## Calling

Import: `from skills.{skill_name} import <func_name>` (`skills.*` = MCP; `tools.*` = built-in; NOT interchangeable).
Docs: `/mcp/{skill_name}/<function_name>.md` — read with `file_read_tool` only when a signature above is abbreviated (`…`) or the return shape matters.

Run ONE `bash_code_execute_tool` per task: `await` every needed call, then emit one `[RESULT]`. Results are parsed Python objects — do NOT `json.loads()`; only access fields explicitly documented. If a return shape is undocumented, emit `[OBSERVATION]` first and continue next call.
Python literals `None`/`True`/`False` (not null/true/false); set `timeout=120` when declared. Loaded once — do not re-select.
"""


class MCPSkillGenerator:
    """MCP service to skill generator with progressive disclosure.

    Three-level progressive disclosure:
    - Level 1: generate_metadata_only() — SkillMetadata with concise description
    - Level 2: generate_skill_content() — full SKILL.md with tool list
    - Level 3: generate_tool_doc() — detailed parameter documentation
    """

    # ========== Level 1: Metadata Generation ==========

    async def generate_metadata_only(self, mcp_configs: list[MCPConfig]) -> list[SkillMetadata]:
        """Generate MCP skill metadata from server configs.

        Acquires a warm pooled session per server (reused later at call time),
        reads its already-loaded tools and ``initialize`` instructions, and
        builds lightweight SkillMetadata. Routing through the pool here means the
        session created during setup is the very one PTC calls reuse — one spawn
        per server for the whole lifecycle, not one per call.

        Description priority: config.description > instructions > auto-generated from tools

        Args:
            mcp_configs: MCP server configuration list

        Returns:
            List of SkillMetadata (one per server)
        """
        if not mcp_configs:
            logger.warning("No MCP configs provided, skipping skill generation")
            return []

        logger.warning("Generating MCP skills from %d server(s)", len(mcp_configs))

        from myrm_agent_harness.toolkits.mcp.connection_manager import (
            get_mcp_connection_manager,
        )

        config_desc_map = {cfg.name: cfg.description for cfg in mcp_configs if cfg.description}
        manager = await get_mcp_connection_manager()

        conn_results = await asyncio.gather(
            *(manager.get_connection([cfg]) for cfg in mcp_configs),
            return_exceptions=True,
        )

        skills: list[SkillMetadata] = []
        claimed_skill_names: dict[str, str] = {}
        for cfg, conn in zip(mcp_configs, conn_results, strict=True):
            if isinstance(conn, BaseException):
                logger.warning("MCP skill gen: server '%s' connect failed: %s", cfg.name, conn)
                continue

            server_tools = conn.tools_by_server.get(cfg.name) or next(
                (tools for tools in conn.tools_by_server.values() if tools), []
            )
            if not server_tools:
                logger.warning("MCP skill gen: server '%s' exposed no tools", cfg.name)
                continue

            instructions = conn.instructions_by_server.get(cfg.name)
            _, base_name = self._get_safe_names(cfg.name)
            skill_name = self._dedupe_skill_name(base_name, claimed_skill_names)
            if skill_name != base_name:
                logger.warning(
                    "MCP skill name collision: servers '%s' and '%s' both normalize to '%s'; "
                    "renaming the latter to '%s' so both stay callable",
                    claimed_skill_names[base_name],
                    cfg.name,
                    base_name,
                    skill_name,
                )
            skill = self._create_skill_metadata(
                cfg.name,
                server_tools,
                config_desc_map.get(cfg.name, ""),
                instructions,
                skill_name=skill_name,
            )
            claimed_skill_names[skill.name] = cfg.name

            if skill.mcp is not None:
                skill.mcp.config = [mcp_config_to_runtime_dict(cfg)]
            skills.append(skill)
            logger.warning("Generated MCP skill: %s (%d tool(s))", skill.name, len(server_tools))

        return skills

    # ========== Level 2: SKILL.md Content ==========

    def generate_skill_content(self, skill_meta: SkillMetadata) -> str:
        """Generate SKILL.md content on-demand (Level 2)."""
        if not skill_meta.mcp:
            return f"# {skill_meta.name}\n\nThis is a local skill, not an MCP skill."

        if skill_meta.mcp.skill_content:
            return skill_meta.mcp.skill_content

        server_name = skill_meta.mcp.server
        tool_schemas = skill_meta.mcp.tool_schemas
        instructions = tool_schemas.get("__instructions__", {}).get("content", "")

        tool_count = len(skill_meta.mcp.tools)
        # The registry matches on skill_meta.name, so L2 must advertise the same string:
        # a server whose name collided was renamed, and recomputing from server_name
        # here would print an import path that no skill answers to.
        skill_name = skill_meta.name
        tools = skill_meta.mcp.tools
        tool_list, tier = build_tool_section(tools, tool_schemas, skill_name, tool_section_budget(instructions))

        usage_section = SKILL_USAGE_TEMPLATE.format(skill_name=skill_name)
        index_note = {
            "names": (
                f"\nThis server exposes {tool_count} tools, so only names are listed. "
                f"Read `/mcp/{skill_name}/<func_name>.md` with `file_read_tool` for the 1-2 tools "
                "you will call, then write the call.\n"
            ),
            "required": (
                "\nSignatures list required parameters only (`…` marks the omitted optionals); "
                "read the tool doc when an optional parameter matters.\n"
            ),
        }.get(tier, "")
        instructions = cap_instructions(instructions, skill_meta.name, INSTRUCTIONS_TOKEN_LIMIT)

        intro = f"{instructions}\n\n" if instructions else ""
        content = f"""# {server_name.replace("_", " ").replace("-", " ").title()} Skill

{intro}**Skill Name**: `{skill_name}` (use this exact name in import paths and doc paths)

## Functions

{tool_list}
{index_note}
{usage_section}
"""

        skill_meta.mcp.skill_content = content
        tokens = get_token_count(content)
        if tokens > L2_MAX_TOKENS:
            logger.warning(
                "MCP SKILL.md for '%s' is %d tokens (soft budget %d); server instructions may need trimming",
                skill_meta.name,
                tokens,
                L2_MAX_TOKENS,
            )
        return content

    # ========== Level 3: Tool Documentation ==========

    def generate_tool_doc(self, skill_meta: SkillMetadata, tool_name: str) -> str:
        """Generate single tool documentation on-demand (Level 3)."""
        if not skill_meta.mcp:
            return f"Error: Skill '{skill_meta.name}' is not an MCP skill."

        mcp_tools = skill_meta.mcp.tools
        matched_tool_name = resolve_mcp_tool_name(tool_name, mcp_tools)

        if not matched_tool_name:
            available_tools = ", ".join(mcp_tools[:5])
            if len(mcp_tools) > 5:
                available_tools += f", ... ({len(mcp_tools)} total)"
            raise FileNotFoundError(
                f"Function '{tool_name}' not found in skill '{skill_meta.name}'. "
                f"Available functions: {available_tools}. "
                f"Please check the tool name and try again."
            )

        if matched_tool_name in skill_meta.mcp.tool_docs:
            return skill_meta.mcp.tool_docs[matched_tool_name]

        schema = skill_meta.mcp.tool_schemas.get(matched_tool_name, {})
        content = self._build_tool_detail_doc(skill_meta, matched_tool_name, schema)

        skill_meta.mcp.tool_docs[matched_tool_name] = content
        return content

    # ========== Internal: Naming ==========

    @staticmethod
    def _get_safe_names(server_name: str) -> tuple[str, str]:
        """Generate safe display name and skill name.

        The skill name becomes a Python package segment (``from skills.<name> import``),
        so every character outside ``[a-z0-9_]`` is folded to ``_``. Collisions produced
        by that folding (``weather`` vs ``weather-skill``) are resolved by
        :meth:`_dedupe_skill_name`, because dropping a server would make it unreachable.

        Returns:
            (display_name, skill_name) tuple
        """
        display_name = server_name.replace("_", " ").replace("-", " ").title()

        skill_name = re.sub(r"[^a-z0-9_]", "_", server_name.replace("-", "_").lower())
        if not skill_name.startswith("mcp_"):
            skill_name = f"mcp_{skill_name}"
        if not skill_name.endswith("_skill"):
            skill_name = f"{skill_name}_skill"

        return display_name, skill_name

    @staticmethod
    def _dedupe_skill_name(base: str, claimed: dict[str, str]) -> str:
        """Return *base* or the first free ``base_<n>`` so every server keeps a skill."""
        if base not in claimed:
            return base
        index = 2
        while f"{base}_{index}" in claimed:
            index += 1
        return f"{base}_{index}"

    # ========== Internal: Tool Documentation ==========

    def _build_tool_detail_doc(
        self,
        skill_meta: SkillMetadata,
        tool_name: str,
        schema: JsonDict,
    ) -> str:
        """Build detailed tool documentation (Level 3)."""
        tool_desc = text_field(schema, "description", "No description available")
        input_schema = normalize_input_schema(schema.get("inputSchema"))
        params_section = build_params_section(input_schema)
        python_func_name = build_tool_name_map(skill_meta.mcp.tools if skill_meta.mcp else [])[tool_name]
        call_example = build_call_example(input_schema)

        return TOOL_DOC_TEMPLATE.format(
            tool_name=python_func_name,
            skill_name=skill_meta.name,
            tool_desc=tool_desc,
            params_section=params_section,
            call_example=call_example,
        )

    def _create_skill_metadata(
        self,
        server_name: str,
        tools: list[BaseTool],
        user_description: str = "",
        instructions: str | None = None,
        *,
        skill_name: str | None = None,
    ) -> SkillMetadata:
        """Create SkillMetadata for a single MCP server.

        Description priority: user_description > instructions > auto-generated from tools

        Args:
            server_name: MCP server name
            tools: Tools from this server
            user_description: User-provided description (from MCPConfig.description)
            instructions: MCP server instructions (from initialize handshake)
            skill_name: Final skill name when the caller already resolved a collision;
                defaults to the name derived from ``server_name``
        """
        tool_names = [tool.name for tool in tools]
        if skill_name is None:
            _, skill_name = self._get_safe_names(server_name)

        skill_description = resolve_description(user_description, instructions, tools, server_name)
        # L1 is the only rendered text that bypassed the load-time scan L2 goes through.
        from myrm_agent_harness.backends.skills.scanning.scanner import ScanSeverity, scan_skill_content

        if any(f.severity >= ScanSeverity.HIGH for f in scan_skill_content(skill_name, skill_description).findings):
            logger.warning("MCP L1 description for '%s' has high-risk scan findings", skill_name)

        tool_schemas: dict[str, dict[str, object]] = {}
        for tool in tools:
            tool_schemas[tool.name] = {
                "description": tool.description,
                "inputSchema": getattr(tool, "args_schema", None),
            }

        tool_schemas["__instructions__"] = {"content": instructions or ""}

        mcp_data = MCPSkillData(server=server_name, tools=tool_names, config=[], tool_schemas=tool_schemas)

        # always=True keeps every MCP server visible in the <bound_skills> catalog while the
        # bound set fits inline, and pins it into the catalog's always-priority band once the set
        # exceeds SKILL_INLINE_THRESHOLD. MCP servers are opaque to the model (nothing in the
        # prompt says a given integration exists), so dropping them to search-only discovery
        # costs a skill_search_tool round trip before the model can even know they exist.
        # Cost: they consume the always band unconditionally, which is why a large MCP fleet can
        # crowd user-authored skills out of the catalog. See catalog_display.resolve_catalog_display_skills.
        return SkillMetadata(name=skill_name, description=skill_description, mcp=mcp_data, always=True)


mcp_skill_generator = MCPSkillGenerator()
