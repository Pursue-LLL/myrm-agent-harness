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

import logging
import re
from typing import Any

from langchain_core.tools import BaseTool

from myrm_agent_harness.agent.skills.mcp.schema_doc_utils import (
    TOOL_DOC_TEMPLATE,
    build_call_example,
    build_params_section,
)
from myrm_agent_harness.backends.skills.types import MCPSkillData, SkillMetadata
from myrm_agent_harness.toolkits.mcp import MCPConfig

logger = logging.getLogger(__name__)

# JSON schema values are inherently untyped; Any is intentional here.
type JsonDict = dict[str, Any]

USAGE_GUIDE_TOOL_THRESHOLD = 3

SKILL_USAGE_TEMPLATE = """
## Usage Guide (Must Follow)

Above are only summaries without parameter details. **Get docs first, then call.**

### Step 1: Read function docs via file_read_tool

Use `file_read_tool` to batch-get docs. Do NOT use bash/cat to read docs — sandbox blocks it.

Path: `/mcp/{{skill_name}}/{{function_name}}.md`

`{{skill_name}}` is the exact name in the "Skill Name" line above. Do NOT guess or abbreviate.

### Step 2: Call via bash_code_execute_tool

Import: `from skills.{{skill_name}} import {{func_name}}` (`skills.*` = MCP; `tools.*` = built-in PTC only, NOT interchangeable)

Rules:
- Returns are **parsed Python objects** — use `result['key']` directly, do NOT `json.loads()`
- Always set `timeout=120` (network round-trips)
- Python syntax only: `None`/`True`/`False` (not null/true/false)

### Performance Rules (CRITICAL)

1. **ONE bash call = ONE complete task** — ENTIRE workflow in a SINGLE invocation. Each extra call wastes ~500ms + thousands of tokens.
2. **Dependency analysis** — combine based on return structure specificity:
   - Independent → `asyncio.gather()` parallel
   - Dependent + known structure (docs show field names/types) → serial in same script
   - Dependent + unknown structure → `print(f"[OBSERVATION] {{result}}")`, combine next call
3. **NEVER re-select this skill** — once loaded, stays available for entire conversation.
4. **No duplicates, converge fast** — never repeat a call with identical params (reuse the fetched result); once data suffices, output immediately — do NOT re-query to double-check.
5. **print() final result** — stdout is your answer.

```python
import asyncio
from skills.{{skill_name}} import func_a, func_b, func_c

async def main():
    a, b = await asyncio.gather(func_a(p1="x"), func_b(p2="y"))
    results = await func_c(from_val=a, to_val=b)
    for item in results[:5]:
        print(f"{{item['name']}} | {{item['value']}}")

asyncio.run(main())
```

"""

class MCPSkillGenerator:
    """MCP service to skill generator with progressive disclosure.

    Three-level progressive disclosure:
    - Level 1: generate_metadata_only() — SkillMetadata with concise description
    - Level 2: generate_skill_content() — full SKILL.md with tool list
    - Level 3: generate_tool_doc() — detailed parameter documentation
    """

    # ========== Level 1: Metadata Generation ==========

    async def generate_metadata_only(
        self, mcp_configs: list[MCPConfig]
    ) -> list[SkillMetadata]:
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

        config_desc_map = {
            cfg.name: cfg.description for cfg in mcp_configs if cfg.description
        }
        manager = await get_mcp_connection_manager()

        skills: list[SkillMetadata] = []
        for cfg in mcp_configs:
            try:
                conn = await manager.get_connection([cfg])
            except Exception as e:
                logger.warning("MCP skill gen: server '%s' connect failed: %s", cfg.name, e)
                continue

            server_tools = conn.tools_by_server.get(cfg.name) or next(
                (tools for tools in conn.tools_by_server.values() if tools), []
            )
            if not server_tools:
                logger.warning("MCP skill gen: server '%s' exposed no tools", cfg.name)
                continue

            instructions = conn.instructions_by_server.get(cfg.name)
            skill = self._create_skill_metadata(
                cfg.name, server_tools, config_desc_map.get(cfg.name, ""), instructions
            )
            skills.append(skill)
            logger.warning(
                "Generated MCP skill: %s (%d tool(s))", skill.name, len(server_tools)
            )

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
        tool_list = self._build_tool_list(
            skill_meta.mcp.tools, tool_schemas, tool_count
        )

        _, skill_name = self._get_safe_names(server_name)

        usage_section = (
            SKILL_USAGE_TEMPLATE.format(skill_name=skill_name)
            if tool_count > USAGE_GUIDE_TOOL_THRESHOLD
            else ""
        )

        intro = f"{instructions}\n\n" if instructions else ""
        content = f"""# {server_name.replace("_", " ").replace("-", " ").title()} Skill

{intro}**Skill Name**: `{skill_name}` (use this exact name in import paths and doc paths)

## Available Functions Overview

{tool_list}

{usage_section}
"""

        skill_meta.mcp.skill_content = content
        return content

    # ========== Level 3: Tool Documentation ==========

    def generate_tool_doc(self, skill_meta: SkillMetadata, tool_name: str) -> str:
        """Generate single tool documentation on-demand (Level 3)."""
        if not skill_meta.mcp:
            return f"Error: Skill '{skill_meta.name}' is not an MCP skill."

        mcp_tools = skill_meta.mcp.tools

        if ":" in tool_name:
            tool_name = tool_name.split(":")[-1]

        matched_tool_name = tool_name if tool_name in mcp_tools else None

        if not matched_tool_name:
            alt_name = tool_name.replace("_", "-")
            if alt_name in mcp_tools:
                matched_tool_name = alt_name
            else:
                alt_name = tool_name.replace("-", "_")
                if alt_name in mcp_tools:
                    matched_tool_name = alt_name

        if not matched_tool_name:
            available_tools = ", ".join(mcp_tools[:5])
            if len(mcp_tools) > 5:
                available_tools += f", ... ({len(mcp_tools)} total)"
            raise FileNotFoundError(
                f"Function '{tool_name}' not found in skill '{skill_meta.name}'. "
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

        Returns:
            (display_name, skill_name) tuple
        """
        display_name = server_name.replace("_", " ").replace("-", " ").title()

        skill_name = server_name.replace("-", "_").lower()
        if not skill_name.startswith("mcp_"):
            skill_name = f"mcp_{skill_name}"
        if not skill_name.endswith("_skill"):
            skill_name = f"{skill_name}_skill"

        return display_name, skill_name

    # ========== Internal: Description Building ==========

    def _resolve_description(
        self,
        user_description: str,
        instructions: str | None,
        tools: list[BaseTool],
        server_name: str,
    ) -> str:
        """Resolve skill description with 3-tier priority.

        Priority: user_description > instructions > auto-generated from tools
        """
        if user_description:
            return user_description

        if instructions:
            clean = self._clean_markdown(instructions)
            return self._truncate_to_sentence(clean, max_len=200)

        return self._build_description_from_tools(tools, server_name)

    def _build_description_from_tools(
        self, tools: list[BaseTool], server_name: str
    ) -> str:
        """Build a concise description from tool descriptions (for metadata)."""
        functions: list[str] = []
        for tool in tools:
            desc = getattr(tool, "description", "")
            if not desc:
                continue
            short = self._truncate_to_sentence(desc, max_len=80)
            if short:
                functions.append(short.rstrip("。."))

        if not functions:
            display = server_name.replace("_", " ").replace("-", " ").title()
            return f"{display} ({len(tools)} tools available)"

        joined = "; ".join(functions[:3])
        suffix = f" and {len(functions) - 3} more" if len(functions) > 3 else ""
        return f"MCP {server_name}: {joined}{suffix}"

    # ========== Internal: Tool List & Documentation ==========

    def _build_tool_list(
        self, tools: list[str], tool_schemas: dict[str, JsonDict], tool_count: int
    ) -> str:
        """Build tool list for SKILL.md.

        Few tools (<=3): show full description with parameters.
        Many tools (>3): truncate to sentence boundary.
        """
        lines = []
        for tool_name in tools:
            schema = tool_schemas.get(tool_name, {})
            desc = schema.get("description", "No description available")
            python_func_name = tool_name.replace("-", "_")

            if tool_count <= USAGE_GUIDE_TOOL_THRESHOLD:
                params_str = self._format_params_inline(schema.get("inputSchema", {}))
                full_desc = (
                    f"{desc}\n\n  **Parameters:**\n{params_str}" if params_str else desc
                )
                full_desc += "\n\n  **Returns:** parsed Python object (do NOT call `json.loads()` on it)"
                lines.append(f"- **{python_func_name}**: {full_desc}")
            else:
                short_desc = self._truncate_to_sentence(desc, max_len=150)
                lines.append(f"- **{python_func_name}**: {short_desc}")

        return "\n\n".join(lines)

    def _build_tool_detail_doc(
        self,
        skill_meta: SkillMetadata,
        tool_name: str,
        schema: JsonDict,
    ) -> str:
        """Build detailed tool documentation (Level 3)."""
        tool_desc = schema.get("description", "No description available")
        input_schema = schema.get("inputSchema", {})
        params_section = build_params_section(input_schema)
        python_func_name = tool_name.replace("-", "_")
        call_example = build_call_example(input_schema)

        return TOOL_DOC_TEMPLATE.format(
            tool_name=python_func_name,
            skill_name=skill_meta.name,
            tool_desc=tool_desc,
            params_section=params_section,
            call_example=call_example,
        )

    # ========== Internal: Parameter Formatting ==========

    @staticmethod
    def _format_params_inline(input_schema: JsonDict) -> str:
        """Format parameters as inline list for SKILL.md tool list.

        Returns empty string if no parameters.
        """
        if not isinstance(input_schema, dict) or "properties" not in input_schema:
            return ""

        properties = input_schema.get("properties", {})
        required = input_schema.get("required", [])

        lines: list[str] = []
        for name, info in properties.items():
            if not isinstance(info, dict):
                continue
            ptype = info.get("type", "any")
            pdesc = info.get("description", "")
            req_tag = " **(required)**" if name in required else ""

            hints: list[str] = []
            if "enum" in info:
                hints.append(f"enum: {info['enum']}")
            if "pattern" in info:
                hints.append(f"pattern: `{info['pattern']}`")
            if "default" in info:
                hints.append(f"default: `{info['default']}`")

            hint_str = f" [{', '.join(hints)}]" if hints else ""
            lines.append(f" - `{name}` ({ptype}){req_tag}: {pdesc}{hint_str}")

        return "\n".join(lines)

    # ========== Internal: Text Processing ==========

    @staticmethod
    def _truncate_to_sentence(text: str, max_len: int = 150) -> str:
        """Truncate text at the first sentence boundary, or at max_len."""
        match = re.search(r"[。.\n]", text)
        if match and match.end() <= max_len:
            return text[: match.end()].strip()
        if len(text) > max_len:
            return text[:max_len].strip() + "..."
        return text

    @staticmethod
    def _clean_markdown(text: str) -> str:
        """Strip markdown formatting from text."""
        text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
        text = re.sub(r"\*([^*]+)\*", r"\1", text)
        text = re.sub(r"#+\s*", "", text)
        return re.sub(r"\n+", " ", text).strip()

    def _create_skill_metadata(
        self,
        server_name: str,
        tools: list[BaseTool],
        user_description: str = "",
        instructions: str | None = None,
    ) -> SkillMetadata:
        """Create SkillMetadata for a single MCP server.

        Description priority: user_description > instructions > auto-generated from tools

        Args:
            server_name: MCP server name
            tools: Tools from this server
            user_description: User-provided description (from MCPConfig.description)
            instructions: MCP server instructions (from initialize handshake)
        """
        tool_names = [tool.name for tool in tools]
        _, skill_name = self._get_safe_names(server_name)

        skill_description = self._resolve_description(
            user_description, instructions, tools, server_name
        )

        tool_schemas: dict[str, dict[str, object]] = {}
        for tool in tools:
            tool_schemas[tool.name] = {
                "description": tool.description,
                "inputSchema": getattr(tool, "args_schema", None),
            }

        tool_schemas["__instructions__"] = {"content": instructions or ""}

        mcp_data = MCPSkillData(
            server=server_name, tools=tool_names, config=[], tool_schemas=tool_schemas
        )

        return SkillMetadata(
            name=skill_name, description=skill_description, mcp=mcp_data
        )


mcp_skill_generator = MCPSkillGenerator()
