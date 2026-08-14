"""Tests for MCP Skill Generator's document templates and tool list building.

Validates that:
- TOOL_DOC_TEMPLATE includes Returns section
- SKILL_USAGE_TEMPLATE includes json.loads() warning
- _build_tool_list includes returns hint for few-tool skills
- generate_tool_doc produces correct documentation
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.skills.mcp.core_generator import (
    SKILL_USAGE_TEMPLATE,
    USAGE_GUIDE_TOOL_THRESHOLD,
    MCPSkillGenerator,
)
from myrm_agent_harness.agent.skills.mcp.schema_doc_utils import TOOL_DOC_TEMPLATE
from myrm_agent_harness.backends.skills.types import MCPSkillData, SkillMetadata


@pytest.fixture
def generator() -> MCPSkillGenerator:
    return MCPSkillGenerator()


@pytest.fixture
def sample_skill_meta() -> SkillMetadata:
    """Minimal SkillMetadata with 2 tools (below threshold), including JSON Schema constraints."""
    tool_schemas: dict[str, dict[str, object]] = {
        "get-tickets": {
            "description": "Query train tickets by date and route",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "Departure date",
                        "format": "date",
                    },
                    "from_station": {"type": "string", "description": "Origin"},
                    "trainFilterFlags": {
                        "type": "string",
                        "description": "Filter flags for train types",
                        "pattern": "^[GDCZTKL]*$",
                        "default": "",
                    },
                    "seat_type": {
                        "type": "string",
                        "description": "Seat category",
                        "enum": [
                            "hard_seat",
                            "soft_seat",
                            "hard_sleeper",
                            "soft_sleeper",
                        ],
                    },
                },
                "required": ["date", "from_station"],
            },
        },
        "get-station-info": {
            "description": "Get station details",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Station name"},
                },
                "required": ["name"],
            },
        },
    }
    mcp = MCPSkillData(
        server="12306-mcp",
        tools=["get-tickets", "get-station-info"],
        config=[],
        tool_schemas=tool_schemas,
    )
    return SkillMetadata(name="mcp_12306_mcp_skill", description="Train tickets", mcp=mcp)


@pytest.fixture
def many_tools_skill_meta() -> SkillMetadata:
    """SkillMetadata with 5 tools (above threshold)."""
    tools = [f"tool-{i}" for i in range(5)]
    schemas: dict[str, dict[str, object]] = {
        name: {"description": f"Tool {i} description", "inputSchema": {}} for i, name in enumerate(tools)
    }
    mcp = MCPSkillData(server="multi-tool", tools=tools, config=[], tool_schemas=schemas)
    return SkillMetadata(name="mcp_multi_tool_skill", description="Many tools", mcp=mcp)


class TestToolDocTemplate:
    """TOOL_DOC_TEMPLATE must inform agents about return value format."""

    def test_contains_returns_section(self) -> None:
        assert "## Returns" in TOOL_DOC_TEMPLATE

    def test_warns_against_json_loads(self) -> None:
        assert "json.loads()" in TOOL_DOC_TEMPLATE

    def test_states_python_object_return(self) -> None:
        assert "parsed Python object" in TOOL_DOC_TEMPLATE


class TestSkillUsageTemplate:
    """SKILL_USAGE_TEMPLATE must guide agents on return value handling."""

    def test_warns_against_json_loads(self) -> None:
        assert "json.loads()" in SKILL_USAGE_TEMPLATE

    def test_mentions_direct_field_access(self) -> None:
        assert "access fields" in SKILL_USAGE_TEMPLATE

    def test_mentions_parallel_pattern(self) -> None:
        assert "asyncio.gather()" in SKILL_USAGE_TEMPLATE

    def test_timeout_guidance_present(self) -> None:
        assert "timeout=120" in SKILL_USAGE_TEMPLATE

    def test_performance_rules_present(self) -> None:
        assert "Performance Rules" in SKILL_USAGE_TEMPLATE


class TestBuildToolListFewTools:
    """_build_tool_list with few tools (<=3) should include returns hint."""

    def test_includes_returns_hint(self, generator: MCPSkillGenerator, sample_skill_meta: SkillMetadata) -> None:
        assert sample_skill_meta.mcp is not None
        tool_list = generator._build_tool_list(
            sample_skill_meta.mcp.tools,
            sample_skill_meta.mcp.tool_schemas,
            len(sample_skill_meta.mcp.tools),
        )
        assert len(sample_skill_meta.mcp.tools) <= USAGE_GUIDE_TOOL_THRESHOLD
        assert "json.loads()" in tool_list
        assert "Returns:" in tool_list

    def test_includes_parameters(self, generator: MCPSkillGenerator, sample_skill_meta: SkillMetadata) -> None:
        assert sample_skill_meta.mcp is not None
        tool_list = generator._build_tool_list(
            sample_skill_meta.mcp.tools,
            sample_skill_meta.mcp.tool_schemas,
            len(sample_skill_meta.mcp.tools),
        )
        assert "Parameters:" in tool_list
        assert "date" in tool_list


class TestBuildToolListManyTools:
    """_build_tool_list with many tools (>3) should NOT inline returns (handled by usage guide)."""

    def test_no_inline_returns(self, generator: MCPSkillGenerator, many_tools_skill_meta: SkillMetadata) -> None:
        assert many_tools_skill_meta.mcp is not None
        tool_list = generator._build_tool_list(
            many_tools_skill_meta.mcp.tools,
            many_tools_skill_meta.mcp.tool_schemas,
            len(many_tools_skill_meta.mcp.tools),
        )
        assert len(many_tools_skill_meta.mcp.tools) > USAGE_GUIDE_TOOL_THRESHOLD
        assert "Returns:" not in tool_list


class TestGenerateToolDoc:
    """generate_tool_doc (Level 3) must include returns section."""

    def test_includes_returns(self, generator: MCPSkillGenerator, sample_skill_meta: SkillMetadata) -> None:
        doc = generator.generate_tool_doc(sample_skill_meta, "get-tickets")
        assert "## Returns" in doc
        assert "json.loads()" in doc

    def test_includes_parameters(self, generator: MCPSkillGenerator, sample_skill_meta: SkillMetadata) -> None:
        doc = generator.generate_tool_doc(sample_skill_meta, "get-tickets")
        assert "## Parameters" in doc
        assert "date" in doc
        assert "from_station" in doc

    def test_uses_python_func_name(self, generator: MCPSkillGenerator, sample_skill_meta: SkillMetadata) -> None:
        doc = generator.generate_tool_doc(sample_skill_meta, "get-tickets")
        assert "get_tickets" in doc

    def test_unknown_tool_raises(self, generator: MCPSkillGenerator, sample_skill_meta: SkillMetadata) -> None:
        with pytest.raises(FileNotFoundError, match="not found"):
            generator.generate_tool_doc(sample_skill_meta, "nonexistent-tool")

    def test_hyphen_underscore_resolution(self, generator: MCPSkillGenerator, sample_skill_meta: SkillMetadata) -> None:
        doc = generator.generate_tool_doc(sample_skill_meta, "get_tickets")
        assert "get_tickets" in doc


class TestSchemaConstraintsInDoc:
    """generate_tool_doc (Level 3) must include JSON Schema constraints."""

    def test_pattern_constraint(self, generator: MCPSkillGenerator, sample_skill_meta: SkillMetadata) -> None:
        doc = generator.generate_tool_doc(sample_skill_meta, "get-tickets")
        assert "Pattern (regex)" in doc
        assert "^[GDCZTKL]*$" in doc

    def test_enum_constraint(self, generator: MCPSkillGenerator, sample_skill_meta: SkillMetadata) -> None:
        doc = generator.generate_tool_doc(sample_skill_meta, "get-tickets")
        assert "Allowed values" in doc
        assert "hard_seat" in doc
        assert "soft_sleeper" in doc

    def test_default_constraint(self, generator: MCPSkillGenerator, sample_skill_meta: SkillMetadata) -> None:
        doc = generator.generate_tool_doc(sample_skill_meta, "get-tickets")
        assert "Default" in doc

    def test_format_constraint(self, generator: MCPSkillGenerator, sample_skill_meta: SkillMetadata) -> None:
        doc = generator.generate_tool_doc(sample_skill_meta, "get-tickets")
        assert "Format" in doc
        assert "date" in doc


class TestSchemaConstraintsInInline:
    """_format_params_inline for few-tool skills must show key constraints."""

    def test_inline_enum_hint(self, generator: MCPSkillGenerator, sample_skill_meta: SkillMetadata) -> None:
        assert sample_skill_meta.mcp is not None
        tool_list = generator._build_tool_list(
            sample_skill_meta.mcp.tools,
            sample_skill_meta.mcp.tool_schemas,
            len(sample_skill_meta.mcp.tools),
        )
        assert "enum:" in tool_list

    def test_inline_pattern_hint(self, generator: MCPSkillGenerator, sample_skill_meta: SkillMetadata) -> None:
        assert sample_skill_meta.mcp is not None
        tool_list = generator._build_tool_list(
            sample_skill_meta.mcp.tools,
            sample_skill_meta.mcp.tool_schemas,
            len(sample_skill_meta.mcp.tools),
        )
        assert "pattern:" in tool_list


class TestGenerateSkillContent:
    """generate_skill_content (Level 2) should include usage guide for many-tool skills."""

    def test_many_tools_includes_usage_guide(
        self, generator: MCPSkillGenerator, many_tools_skill_meta: SkillMetadata
    ) -> None:
        content = generator.generate_skill_content(many_tools_skill_meta)
        assert "Usage Guide" in content
        assert "json.loads()" in content

    def test_few_tools_no_usage_guide(self, generator: MCPSkillGenerator, sample_skill_meta: SkillMetadata) -> None:
        content = generator.generate_skill_content(sample_skill_meta)
        assert "Usage Guide" not in content
        assert "Returns:" in content

    def test_skill_content_includes_skill_name(
        self, generator: MCPSkillGenerator, many_tools_skill_meta: SkillMetadata
    ) -> None:
        content = generator.generate_skill_content(many_tools_skill_meta)
        assert "Skill Name" in content
        assert "mcp_" in content


class TestToolDocImportExample:
    """Tool doc (Level 3) should include import path and call example."""

    def test_import_example_present(self, generator: MCPSkillGenerator, sample_skill_meta: SkillMetadata) -> None:
        doc = generator.generate_tool_doc(sample_skill_meta, "get-tickets")
        assert "from skills." in doc
        assert "import get_tickets" in doc
        assert "from skills." in doc and " import " in doc

    def test_import_warning_present(self, generator: MCPSkillGenerator, sample_skill_meta: SkillMetadata) -> None:
        doc = generator.generate_tool_doc(sample_skill_meta, "get-tickets")
        assert "Do NOT call" in doc
        assert "json.loads()" in doc

    def test_call_example_has_required_params(
        self, generator: MCPSkillGenerator, sample_skill_meta: SkillMetadata
    ) -> None:
        doc = generator.generate_tool_doc(sample_skill_meta, "get-tickets")
        assert "date=" in doc


class TestBuildCallExample:
    """build_call_example should generate correct parameter examples."""

    def test_string_param(self) -> None:
        from myrm_agent_harness.agent.skills.mcp.schema_doc_utils import (
            build_call_example,
        )

        schema = {"properties": {"name": {"type": "string"}}, "required": ["name"]}
        result = build_call_example(schema)
        assert 'name="..."' in result

    def test_example_value_used(self) -> None:
        from myrm_agent_harness.agent.skills.mcp.schema_doc_utils import (
            build_call_example,
        )

        schema = {
            "properties": {"city": {"type": "string", "examples": ["Beijing"]}},
            "required": ["city"],
        }
        result = build_call_example(schema)
        assert 'city="Beijing"' in result

    def test_optional_params_excluded(self) -> None:
        from myrm_agent_harness.agent.skills.mcp.schema_doc_utils import (
            build_call_example,
        )

        schema = {
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["query"],
        }
        result = build_call_example(schema)
        assert "query=" in result
        assert "limit=" not in result

    def test_empty_schema(self) -> None:
        from myrm_agent_harness.agent.skills.mcp.schema_doc_utils import (
            build_call_example,
        )

        assert build_call_example({}) == ""
        assert build_call_example({"properties": {}}) == ""


class TestSkillUsageTemplateSecurity:
    """SKILL_USAGE_TEMPLATE should warn against bash cat and wrong import paths."""

    def test_forbids_bash_cat(self) -> None:
        assert "NOT bash/cat" in SKILL_USAGE_TEMPLATE or "Do NOT use" in SKILL_USAGE_TEMPLATE

    def test_import_path_guidance(self) -> None:
        assert "from skills." in SKILL_USAGE_TEMPLATE
        assert "tools.*" in SKILL_USAGE_TEMPLATE
        assert "NOT interchangeable" in SKILL_USAGE_TEMPLATE

    def test_skill_name_guidance(self) -> None:
        assert "Skill Name" in SKILL_USAGE_TEMPLATE or "skill_name" in SKILL_USAGE_TEMPLATE

    def test_python_syntax_guidance(self) -> None:
        assert "None" in SKILL_USAGE_TEMPLATE and "null" in SKILL_USAGE_TEMPLATE
        assert "True" in SKILL_USAGE_TEMPLATE and "False" in SKILL_USAGE_TEMPLATE
        assert "var" in SKILL_USAGE_TEMPLATE or "let" in SKILL_USAGE_TEMPLATE


class TestCreateSkillMetadata:
    def test_mcp_skill_metadata_always_inline(self, generator: MCPSkillGenerator) -> None:
        from unittest.mock import MagicMock

        tool = MagicMock()
        tool.name = "mcp__12306__get_tickets"
        tool.description = "Query tickets"
        tool.args_schema = None

        meta = generator._create_skill_metadata("12306", [tool], user_description="12306 tickets")
        assert meta.always is True
        assert meta.is_mcp_skill is True


class TestGenerateSkillContentEdgeCases:
    """generate_skill_content edge paths: non-MCP skill + cached content."""

    def test_non_mcp_skill_returns_local_notice(self, generator: MCPSkillGenerator) -> None:
        meta = SkillMetadata(name="local_skill", description="Local skill")
        content = generator.generate_skill_content(meta)
        assert "local skill" in content
        assert "not an MCP skill" in content

    def test_cached_skill_content_returned(
        self, generator: MCPSkillGenerator, many_tools_skill_meta: SkillMetadata
    ) -> None:
        assert many_tools_skill_meta.mcp is not None
        many_tools_skill_meta.mcp.skill_content = "cached-skill-content"
        assert generator.generate_skill_content(many_tools_skill_meta) == "cached-skill-content"


class TestGenerateToolDocEdgeCases:
    """generate_tool_doc edge paths: non-MCP + cached doc + many-tool truncation."""

    def test_non_mcp_skill_returns_error(self, generator: MCPSkillGenerator) -> None:
        meta = SkillMetadata(name="local_skill", description="Local")
        result = generator.generate_tool_doc(meta, "some-tool")
        assert "not an MCP skill" in result

    def test_cached_tool_doc_returned(self, generator: MCPSkillGenerator, sample_skill_meta: SkillMetadata) -> None:
        assert sample_skill_meta.mcp is not None
        sample_skill_meta.mcp.tool_docs["get-tickets"] = "cached-tool-doc"
        assert generator.generate_tool_doc(sample_skill_meta, "get-tickets") == "cached-tool-doc"

    def test_unknown_tool_many_tools_truncates_available(self, generator: MCPSkillGenerator) -> None:
        names = [f"tool-{i}" for i in range(6)]
        schemas = {name: {"description": f"Desc {i}", "inputSchema": {}} for i, name in enumerate(names)}
        mcp = MCPSkillData(server="srv", tools=names, config=[], tool_schemas=schemas)
        meta = SkillMetadata(name="mcp_srv_skill", description="Srv", mcp=mcp)
        with pytest.raises(FileNotFoundError, match="not found"):
            generator.generate_tool_doc(meta, "missing-tool")


class TestResolveDescriptionPriority:
    """_resolve_description priority: user > instructions > auto-generated."""

    def test_user_description_wins(self, generator: MCPSkillGenerator) -> None:
        assert generator._resolve_description("user desc", "instr", [], "srv") == "user desc"

    def test_instructions_fallback_cleans_markdown(self, generator: MCPSkillGenerator) -> None:
        desc = generator._resolve_description("", "**Hello** world.\n\nExtra", [], "srv")
        assert "Hello world" in desc

    def test_auto_generated_from_tool_descriptions(self, generator: MCPSkillGenerator) -> None:
        from types import SimpleNamespace

        tools = [SimpleNamespace(description="Query tickets quickly.")]
        desc = generator._resolve_description("", None, tools, "srv")
        assert "Query tickets quickly" in desc
        assert "srv" in desc

    def test_auto_generated_no_descriptions(self, generator: MCPSkillGenerator) -> None:
        from types import SimpleNamespace

        tools = [SimpleNamespace(description=""), SimpleNamespace(description="")]
        desc = generator._resolve_description("", None, tools, "my-server")
        assert desc == "My Server (2 tools available)"

    def test_auto_generated_more_than_three(self, generator: MCPSkillGenerator) -> None:
        from types import SimpleNamespace

        tools = [SimpleNamespace(description=f"Desc {i} tool.") for i in range(5)]
        desc = generator._resolve_description("", None, tools, "srv")
        assert "and 2 more" in desc


class TestFormatParamsInlineEdge:
    """_format_params_inline edge paths."""

    def test_empty_schema(self, generator: MCPSkillGenerator) -> None:
        assert generator._format_params_inline({}) == ""

    def test_non_dict_param_info_skipped(self, generator: MCPSkillGenerator) -> None:
        schema = {"type": "object", "properties": {"weird": "not-a-dict"}}
        assert generator._format_params_inline(schema) == ""


class TestTextProcessing:
    """_truncate_to_sentence and _clean_markdown."""

    def test_truncate_at_sentence_boundary(self) -> None:
        assert MCPSkillGenerator._truncate_to_sentence("Hello world. Next", max_len=20) == "Hello world."

    def test_truncate_long_text(self) -> None:
        result = MCPSkillGenerator._truncate_to_sentence("x" * 100, max_len=50)
        assert result == "x" * 50 + "..."
        assert len(result) == 53

    def test_truncate_short_text(self) -> None:
        assert MCPSkillGenerator._truncate_to_sentence("short", max_len=50) == "short"

    def test_clean_markdown(self) -> None:
        assert MCPSkillGenerator._clean_markdown("**bold** and *italic* and # heading") == "bold and italic and heading"


class TestGenerateMetadataOnly:
    """generate_metadata_only with mocked connection manager."""

    async def test_empty_configs_returns_empty(self, generator: MCPSkillGenerator) -> None:
        assert await generator.generate_metadata_only([]) == []

    async def test_generates_skills_from_configs(
        self, generator: MCPSkillGenerator, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, MagicMock

        from myrm_agent_harness.toolkits.mcp import connection_manager as cm
        from myrm_agent_harness.toolkits.mcp.config import MCPConfig

        fake_manager = MagicMock()
        fake_conn = MagicMock()
        fake_conn.tools_by_server = {
            "srv": [
                SimpleNamespace(
                    name="mcp__srv__tool-a",
                    description="Tool A",
                    args_schema=None,
                ),
                SimpleNamespace(
                    name="mcp__srv__tool-b",
                    description="Tool B",
                    args_schema=None,
                ),
            ]
        }
        fake_conn.instructions_by_server = {"srv": "Use carefully"}
        fake_manager.get_connection = AsyncMock(return_value=fake_conn)
        monkeypatch.setattr(cm, "get_mcp_connection_manager", AsyncMock(return_value=fake_manager))

        cfg = MCPConfig(name="srv", type="stdio", command="echo", description="srv desc")
        skills = await generator.generate_metadata_only([cfg])
        assert len(skills) == 1
        assert skills[0].is_mcp_skill is True
        assert skills[0].name == "mcp_srv_skill"
