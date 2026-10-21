"""Tests for MCP Skill Generator's document templates and tool list building.

Validates that:
- TOOL_DOC_TEMPLATE includes Returns section
- SKILL_USAGE_TEMPLATE carries the call contract without duplicating bash guidance
- _build_tool_list renders compact signatures (N<=limit) or an index (N>limit)
- generate_tool_doc produces correct documentation
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.skills.mcp.core_generator import (
    SKILL_USAGE_TEMPLATE,
    MCPSkillGenerator,
    mcp_skill_generator,
)
from myrm_agent_harness.agent.skills.mcp.description import resolve_description
from myrm_agent_harness.agent.skills.mcp.doc_rendering import (
    INDEX_NOTE_TOKENS,
    INSTRUCTIONS_TOKEN_LIMIT,
    L2_FIXED_TOKENS,
    L2_MAX_TOKENS,
    MIN_TOOL_SECTION_TOKENS,
    build_tool_section,
    clean_markdown,
    tool_section_budget,
    truncate_to_sentence,
)
from myrm_agent_harness.agent.skills.mcp.schema_doc_utils import TOOL_DOC_TEMPLATE, render_signature
from myrm_agent_harness.backends.skills.types import MCPSkillData, SkillMetadata
from myrm_agent_harness.utils.text_utils import get_token_count


def _tool_section(generator, tools, schemas, **kwargs):
    """L2 tool-section text for the tier the budget ladder picks."""
    return build_tool_section(tools, schemas, kwargs.get("skill_name", ""), tool_section_budget(""))[0]


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
    """SkillMetadata with 5 tools (signature path)."""
    tools = [f"tool-{i}" for i in range(5)]
    schemas: dict[str, dict[str, object]] = {
        name: {"description": f"Tool {i} description", "inputSchema": {}} for i, name in enumerate(tools)
    }
    mcp = MCPSkillData(server="multi-tool", tools=tools, config=[], tool_schemas=schemas)
    return SkillMetadata(name="mcp_multi_tool_skill", description="Many tools", mcp=mcp)


@pytest.fixture
def large_skill_meta() -> SkillMetadata:
    """SkillMetadata whose tool section exceeds the budget ladder's signature rungs."""
    tools = [f"tool-{i}" for i in range(400)]
    schemas: dict[str, dict[str, object]] = {
        name: {"description": f"Tool {i} description", "inputSchema": {}} for i, name in enumerate(tools)
    }
    mcp = MCPSkillData(server="large", tools=tools, config=[], tool_schemas=schemas)
    return SkillMetadata(name="mcp_large_skill", description="Large server", mcp=mcp)


class TestToolDocTemplate:
    """TOOL_DOC_TEMPLATE must inform agents about return value format."""

    def test_contains_returns_section(self) -> None:
        assert "## Returns" in TOOL_DOC_TEMPLATE

    def test_warns_against_json_loads(self) -> None:
        assert "json.loads()" in TOOL_DOC_TEMPLATE

    def test_states_python_object_return(self) -> None:
        assert "parsed Python object" in TOOL_DOC_TEMPLATE


class TestSkillUsageTemplate:
    """SKILL_USAGE_TEMPLATE carries the MCP-specific call contract only."""

    def test_warns_against_json_loads(self) -> None:
        assert "json.loads()" in SKILL_USAGE_TEMPLATE

    def test_mentions_direct_field_access(self) -> None:
        assert "access fields" in SKILL_USAGE_TEMPLATE

    def test_mentions_one_bash_per_task(self) -> None:
        assert "ONE `bash_code_execute_tool`" in SKILL_USAGE_TEMPLATE
        assert "[RESULT]" in SKILL_USAGE_TEMPLATE

    def test_timeout_guidance_present(self) -> None:
        assert "timeout=120" in SKILL_USAGE_TEMPLATE

    def test_does_not_duplicate_bash_scenarios(self) -> None:
        """Scenario A/B/C live in bash_code_execute_tool's own description."""
        assert "Scenario A" not in SKILL_USAGE_TEMPLATE
        assert "Scenario B" not in SKILL_USAGE_TEMPLATE

    def test_does_not_force_doc_read_before_bash(self) -> None:
        assert "Do NOT start bash until" not in SKILL_USAGE_TEMPLATE


class TestBuildToolListFewTools:
    """_build_tool_list renders a signature line per tool."""

    def test_includes_parameter_names_and_types(
        self, generator: MCPSkillGenerator, sample_skill_meta: SkillMetadata
    ) -> None:
        assert sample_skill_meta.mcp is not None
        tool_list = _tool_section(
            generator,
            sample_skill_meta.mcp.tools,
            sample_skill_meta.mcp.tool_schemas,
            skill_name=sample_skill_meta.name,
        )
        assert "get_tickets(" in tool_list
        assert "date:string" in tool_list
        assert "from_station:string" in tool_list
        assert "seat_type?:string" in tool_list

    def test_inlines_short_pattern(self, generator: MCPSkillGenerator, sample_skill_meta: SkillMetadata) -> None:
        assert sample_skill_meta.mcp is not None
        tool_list = _tool_section(
            generator,
            sample_skill_meta.mcp.tools,
            sample_skill_meta.mcp.tool_schemas,
        )
        assert "~^[GDCZTKL]*$" in tool_list

    def test_omits_long_enum(self, generator: MCPSkillGenerator, sample_skill_meta: SkillMetadata) -> None:
        """A four-value enum exceeds the inline budget and stays in the doc."""
        assert sample_skill_meta.mcp is not None
        tool_list = _tool_section(
            generator,
            sample_skill_meta.mcp.tools,
            sample_skill_meta.mcp.tool_schemas,
        )
        assert "hard_sleeper" not in tool_list

    def test_no_inline_returns_block(self, generator: MCPSkillGenerator, sample_skill_meta: SkillMetadata) -> None:
        assert sample_skill_meta.mcp is not None
        tool_list = _tool_section(
            generator,
            sample_skill_meta.mcp.tools,
            sample_skill_meta.mcp.tool_schemas,
        )
        assert "Returns:" not in tool_list


class TestBuildToolListIndex:
    """Above the signature limit only names and first sentences are listed."""

    def test_large_server_has_no_signatures(
        self, generator: MCPSkillGenerator, large_skill_meta: SkillMetadata
    ) -> None:
        assert large_skill_meta.mcp is not None
        tool_list = _tool_section(
            generator,
            large_skill_meta.mcp.tools,
            large_skill_meta.mcp.tool_schemas,
        )
        assert "(" not in tool_list
        assert "tool_0" in tool_list

    def test_duplicate_short_names_get_distinct_identifiers(self, generator: MCPSkillGenerator) -> None:
        tools = ["mcp__srv__get-ticket", "mcp__srv__get_ticket"]
        schemas = {
            name: {"description": "Query", "inputSchema": {"properties": {"a": {"type": "string"}}}} for name in tools
        }
        tool_list = _tool_section(generator, tools, schemas)
        # Both stay callable: the second takes a deterministic suffix instead of being marked dead.
        assert "get_ticket(a?:string)" in tool_list
        assert "get_ticket_2(a?:string)" in tool_list

    def test_large_server_lists_names_without_descriptions(
        self, generator: MCPSkillGenerator, large_skill_meta: SkillMetadata
    ) -> None:
        assert large_skill_meta.mcp is not None
        content = generator.generate_skill_content(large_skill_meta)
        assert "- tool_0\n" in content
        assert "Tool 0 description" not in content
        assert "only names are listed" in content


class TestInstructionsCap:
    """Server instructions are bounded so one verbose server cannot blow up L2."""

    def test_long_instructions_are_truncated(self, generator: MCPSkillGenerator) -> None:
        long_text = "必须遵守的规则。" * 1_000
        schemas: dict[str, dict[str, object]] = {
            "__instructions__": {"content": long_text},
            "fn_0": {"description": "Fn", "inputSchema": {"properties": {"a": {"type": "string"}}}},
        }
        mcp = MCPSkillData(server="verbose", tools=["fn_0"], config=[], tool_schemas=schemas)
        meta = SkillMetadata(name="mcp_verbose_skill", description="d", mcp=mcp)
        content = generator.generate_skill_content(meta)
        assert "instructions truncated" in content
        assert content.count("必须遵守的规则") < 1_000

    def test_short_instructions_are_untouched(self, generator: MCPSkillGenerator) -> None:
        schemas: dict[str, dict[str, object]] = {
            "__instructions__": {"content": "必要时追问。"},
            "fn_0": {"description": "Fn", "inputSchema": {}},
        }
        mcp = MCPSkillData(server="brief", tools=["fn_0"], config=[], tool_schemas=schemas)
        meta = SkillMetadata(name="mcp_brief_skill", description="d", mcp=mcp)
        content = generator.generate_skill_content(meta)
        assert "必要时追问。" in content
        assert "truncated" not in content


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
    """Signature lines must keep constraint hints that fit inline."""

    def test_inline_pattern_hint(self, generator: MCPSkillGenerator, sample_skill_meta: SkillMetadata) -> None:
        assert sample_skill_meta.mcp is not None
        tool_list = _tool_section(
            generator,
            sample_skill_meta.mcp.tools,
            sample_skill_meta.mcp.tool_schemas,
        )
        assert "~^[GDCZTKL]*$" in tool_list

    def test_inline_short_enum_hint(self, generator: MCPSkillGenerator) -> None:
        schemas: dict[str, dict[str, object]] = {
            "fmt": {
                "description": "Format",
                "inputSchema": {
                    "properties": {"f": {"type": "string", "enum": ["text", "csv", "json"]}},
                    "required": ["f"],
                },
            }
        }
        tool_list = _tool_section(generator, ["fmt"], schemas)
        assert "=text|csv|json" in tool_list


class TestGenerateSkillContent:
    """generate_skill_content (Level 2) always carries the calling contract."""

    def test_many_tools_includes_calling_guide(
        self, generator: MCPSkillGenerator, many_tools_skill_meta: SkillMetadata
    ) -> None:
        content = generator.generate_skill_content(many_tools_skill_meta)
        assert "## Calling" in content
        assert "json.loads()" in content

    def test_few_tools_also_includes_calling_guide(
        self, generator: MCPSkillGenerator, sample_skill_meta: SkillMetadata
    ) -> None:
        """Small servers used to get no import path at all; the contract is unconditional now."""
        content = generator.generate_skill_content(sample_skill_meta)
        assert "## Calling" in content
        assert "from skills." in content
        assert "file_read_tool" in content

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

    def test_dot_path_uses_dict_splat(self) -> None:
        """Flattened schemas use dotted names that are not valid Python keywords."""
        from myrm_agent_harness.agent.skills.mcp.schema_doc_utils import (
            build_call_example,
        )

        schema = {"properties": {"config.timeout": {"type": "integer"}}, "required": ["config.timeout"]}
        example = build_call_example(schema)
        assert example == '**{"config.timeout": 0}'
        compile(f"async def _m():\n    await call({example})", "<example>", "exec")


class TestSkillUsageTemplateSecurity:
    """SKILL_USAGE_TEMPLATE keeps import-path and literal guidance."""

    def test_import_path_guidance(self) -> None:
        assert "from skills." in SKILL_USAGE_TEMPLATE
        assert "tools.*" in SKILL_USAGE_TEMPLATE
        assert "NOT interchangeable" in SKILL_USAGE_TEMPLATE

    def test_skill_name_guidance(self) -> None:
        assert "Skill Name" in SKILL_USAGE_TEMPLATE or "skill_name" in SKILL_USAGE_TEMPLATE

    def test_python_syntax_guidance(self) -> None:
        assert "None" in SKILL_USAGE_TEMPLATE and "null" in SKILL_USAGE_TEMPLATE
        assert "True" in SKILL_USAGE_TEMPLATE and "False" in SKILL_USAGE_TEMPLATE


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
        desc = resolve_description("user desc", "instr", [], "srv")
        assert desc == "user desc"

    def test_no_trigger_sentence_is_appended(self, generator: MCPSkillGenerator) -> None:
        # The catalog routing rules own skill selection; per-server imperatives contradicted them.
        assert resolve_description("Use when handling tickets", "instr", [], "srv") == ("Use when handling tickets")
        assert "必须首先选择本技能" not in resolve_description("tickets", "", [], "srv")

    def test_instructions_fallback_cleans_markdown(self, generator: MCPSkillGenerator) -> None:
        desc = resolve_description("", "**Hello** world.\n\nExtra", [], "srv")
        assert "Hello world" in desc

    def test_auto_generated_from_tool_descriptions(self, generator: MCPSkillGenerator) -> None:
        from types import SimpleNamespace

        tools = [SimpleNamespace(description="Query tickets quickly.")]
        desc = resolve_description("", None, tools, "srv")
        assert "Query tickets quickly" in desc
        assert "srv" in desc

    def test_auto_generated_no_descriptions(self, generator: MCPSkillGenerator) -> None:
        from types import SimpleNamespace

        tools = [SimpleNamespace(description=""), SimpleNamespace(description="")]
        desc = resolve_description("", None, tools, "my-server")
        assert desc == "My Server (2 tools available)"

    def test_auto_generated_more_than_three(self, generator: MCPSkillGenerator) -> None:
        from types import SimpleNamespace

        tools = [SimpleNamespace(description=f"Desc {i} tool.") for i in range(5)]
        desc = resolve_description("", None, tools, "srv")
        assert "and 2 more" in desc


class TestRenderSignatureEdge:
    """Signature rendering edge paths."""

    def test_empty_schema_renders_zero_args(self, generator: MCPSkillGenerator) -> None:
        assert render_signature("noop", {}) == "noop()"

    def test_non_dict_param_info_skipped(self, generator: MCPSkillGenerator) -> None:
        schema = {"type": "object", "properties": {"weird": "not-a-dict"}}
        # A malformed properties map means "unknown parameters", not "no parameters".
        assert render_signature("fn", schema) == "fn(…)"

    def test_type_list_drops_null(self, generator: MCPSkillGenerator) -> None:
        schema = {"properties": {"q": {"type": ["string", "null"]}}}
        assert render_signature("fn", schema) == "fn(q?:string)"

    def test_anyof_union(self, generator: MCPSkillGenerator) -> None:
        schema = {"properties": {"q": {"anyOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]}}}
        assert render_signature("fn", schema) == "fn(q?:string|array)"

    def test_missing_type_defaults_to_any(self, generator: MCPSkillGenerator) -> None:
        schema = {"properties": {"q": {"description": "free form"}}}
        assert render_signature("fn", schema) == "fn(q?:any)"

    def test_long_pattern_not_inlined(self, generator: MCPSkillGenerator) -> None:
        schema = {"properties": {"q": {"type": "string", "pattern": "x" * 40}}}
        assert "~" not in render_signature("fn", schema)


class TestSafeNames:
    """Skill names become Python package segments."""

    def test_dot_is_sanitized(self, generator: MCPSkillGenerator) -> None:
        _, skill_name = generator._get_safe_names("my.server")
        assert skill_name == "mcp_my_server_skill"

    def test_colliding_servers_normalize_to_the_same_name(self, generator: MCPSkillGenerator) -> None:
        assert generator._get_safe_names("weather")[1] == generator._get_safe_names("weather-skill")[1]


class TestTextProcessing:
    """_truncate_to_sentence and _clean_markdown."""

    def test_truncate_at_sentence_boundary(self) -> None:
        assert truncate_to_sentence("Hello world. Next", max_len=20) == "Hello world."

    def test_truncate_long_text(self) -> None:
        result = truncate_to_sentence("x" * 100, max_len=50)
        assert result == "x" * 50 + "..."
        assert len(result) == 53

    def test_truncate_short_text(self) -> None:
        assert truncate_to_sentence("short", max_len=50) == "short"

    def test_clean_markdown(self) -> None:
        assert clean_markdown("**bold** and *italic* and # heading") == "bold and italic and heading"


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

    async def test_colliding_skill_names_are_disambiguated(
        self, generator: MCPSkillGenerator, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """weather and weather-skill normalize to the same name; the later one is renamed, not dropped."""
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, MagicMock

        from myrm_agent_harness.toolkits.mcp import connection_manager as cm
        from myrm_agent_harness.toolkits.mcp.config import MCPConfig

        fake_manager = MagicMock()
        fake_conn = MagicMock()
        fake_conn.tools_by_server = {
            "weather": [SimpleNamespace(name="mcp__weather__get", description="Weather", args_schema=None)]
        }
        fake_conn.instructions_by_server = {}
        fake_manager.get_connection = AsyncMock(return_value=fake_conn)
        monkeypatch.setattr(cm, "get_mcp_connection_manager", AsyncMock(return_value=fake_manager))

        skills = await generator.generate_metadata_only(
            [
                MCPConfig(name="weather", type="stdio", command="echo"),
                MCPConfig(name="weather-skill", type="stdio", command="echo"),
            ]
        )
        assert [skill.name for skill in skills] == ["mcp_weather_skill", "mcp_weather_skill_2"]


class TestToolSectionLadder:
    """The tool section degrades by budget, never by a raw tool count."""

    @staticmethod
    def _schemas(count: int) -> dict[str, dict[str, object]]:
        return {
            f"tool_{i}": {
                "description": "Query records and return matches.",
                "inputSchema": {
                    "properties": {f"p{j}": {"type": "string"} for j in range(6)},
                    "required": ["p0", "p1"],
                },
            }
            for i in range(count)
        }

    def test_twenty_one_tools_keep_full_signatures(self) -> None:
        # The old count threshold dropped every parameter at 21 tools.
        schemas = self._schemas(21)
        tool_list = build_tool_section(list(schemas), schemas, "x", 1_600)[0]
        assert "p5?:string" in tool_list
        assert "…" not in tool_list
        assert get_token_count(tool_list) <= 1_600

    def test_budget_reserves_the_tier_note(self) -> None:
        # The tier note is appended after the tool section; the budget must leave room for it.
        assert L2_FIXED_TOKENS + INSTRUCTIONS_TOKEN_LIMIT + MIN_TOOL_SECTION_TOKENS + INDEX_NOTE_TOKENS == L2_MAX_TOKENS
        assert tool_section_budget("") == L2_MAX_TOKENS - L2_FIXED_TOKENS - INDEX_NOTE_TOKENS
        assert tool_section_budget("token " * 3_000) == MIN_TOOL_SECTION_TOKENS

        long_skill = "mcp_" + "x" * 200 + "_skill"
        note = (
            f"\nThis server exposes 300 tools, so only names are listed. "
            f"Read `/mcp/{long_skill}/<func_name>.md` with `file_read_tool` for the 1-2 tools "
            "you will call, then write the call.\n"
        )
        assert get_token_count(note) <= INDEX_NOTE_TOKENS

    def test_names_tier_respects_budget(self) -> None:
        # A verbose server with hundreds of tools cannot fit every name inside the ceiling.
        schemas = self._schemas(300)
        budget = tool_section_budget("token " * 3_000)
        tool_list = build_tool_section(list(schemas), schemas, "x", budget)[0]
        assert get_token_count(tool_list) <= budget
        assert "more tools not shown" in tool_list

    def test_fifty_tools_drop_optionals_but_keep_required(self) -> None:
        schemas = self._schemas(50)
        tool_list = build_tool_section(list(schemas), schemas, "x", 1_200)[0]
        assert "p0:string" in tool_list
        assert "p5?:string" not in tool_list
        assert "…" in tool_list
        assert get_token_count(tool_list) <= 1_200

    def test_two_hundred_tools_fall_back_to_names(self) -> None:
        schemas = self._schemas(200)
        tool_list = _tool_section(mcp_skill_generator, list(schemas), schemas)
        assert "(" not in tool_list
        assert tool_list.count("- tool_") == 200
