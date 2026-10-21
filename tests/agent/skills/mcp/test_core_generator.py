"""Unit tests for MCPSkillGenerator progressive-disclosure generation.

[INPUT]
- myrm_agent_harness.agent.skills.mcp::core_generator (POS: MCP-to-skill generator)
- myrm_agent_harness.backends.skills::types (POS: SkillMetadata / MCPSkillData)

[OUTPUT]
- Coverage of generate_metadata_only / generate_skill_content / generate_tool_doc
  and the naming, description, tool-list, and text-processing helpers.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from myrm_agent_harness.agent.skills.mcp.core_generator import (
    SKILL_USAGE_TEMPLATE,
    MCPSkillGenerator,
    mcp_skill_generator,
)
from myrm_agent_harness.agent.skills.mcp.description import build_description_from_tools, resolve_description
from myrm_agent_harness.agent.skills.mcp.doc_rendering import (
    build_tool_section,
    clean_markdown,
    tool_section_budget,
    truncate_to_sentence,
)
from myrm_agent_harness.agent.skills.mcp.schema_doc_utils import render_signature
from myrm_agent_harness.backends.skills.types import SkillMetadata
from myrm_agent_harness.backends.skills.types.types_requires import MCPSkillData
from myrm_agent_harness.utils.text_utils import get_token_count


def _tool_section(generator, tools, schemas, **kwargs):
    """L2 tool-section text for the tier the budget ladder picks."""
    return build_tool_section(tools, schemas, kwargs.get("skill_name", ""), tool_section_budget(""))[0]


def _skill_meta(
    server: str,
    tools: list[str],
    schemas: dict[str, dict[str, object]] | None = None,
    cached_content: str | None = None,
) -> SkillMetadata:
    mcp = MCPSkillData(
        server=server,
        tools=tools,
        config=[],
        skill_content=cached_content,
        tool_schemas=schemas or {},
    )
    return SkillMetadata(name=f"mcp_{server}_skill", description="desc", mcp=mcp)


class TestGenerateSkillContent:
    def test_local_skill_returns_local_notice(self) -> None:
        meta = SkillMetadata(name="local_skill", description="desc", mcp=None)
        out = mcp_skill_generator.generate_skill_content(meta)
        assert out.startswith(f"# {meta.name}")
        assert "local skill" in out

    def test_cached_content_returned_unchanged(self) -> None:
        meta = _skill_meta("weather", ["get_temp"], cached_content="# cached")
        assert mcp_skill_generator.generate_skill_content(meta) == "# cached"

    def test_few_tools_still_get_calling_contract(self) -> None:
        """A small server used to get no import path at all."""
        meta = _skill_meta("weather", ["get_temp"])
        out = mcp_skill_generator.generate_skill_content(meta)
        assert "## Calling" in out
        assert "from skills." in out
        assert "get_temp" in out

    def test_many_tools_embed_calling_contract(self) -> None:
        tools = [f"func_{i}" for i in range(5)]
        meta = _skill_meta("weather", tools)
        out = mcp_skill_generator.generate_skill_content(meta)
        assert "## Calling" in out
        assert "Skill Name" in out
        assert "mcp_weather_skill" in out
        for fragment in (
            "[RESULT]",
            "OBSERVATION",
            "skills.mcp_weather_skill",
            "file_read_tool",
        ):
            assert fragment in out, fragment

    def test_skill_content_cached_after_generation(self) -> None:
        tools = [f"func_{i}" for i in range(5)]
        meta = _skill_meta("weather", tools)
        mcp_skill_generator.generate_skill_content(meta)
        assert meta.mcp is not None
        assert meta.mcp.skill_content is not None
        assert "## Calling" in meta.mcp.skill_content


class TestGenerateToolDoc:
    def test_local_skill_returns_error(self) -> None:
        meta = SkillMetadata(name="local_skill", description="desc", mcp=None)
        out = mcp_skill_generator.generate_tool_doc(meta, "anything")
        assert "not an MCP skill" in out

    def test_unknown_tool_raises_with_available_list(self) -> None:
        meta = _skill_meta("weather", ["get_temp", "get_wind"])
        with pytest.raises(FileNotFoundError) as exc:
            mcp_skill_generator.generate_tool_doc(meta, "missing_fn")
        msg = str(exc.value)
        assert "missing_fn" in msg
        assert "get_temp" in msg
        assert "get_wind" in msg

    def test_unknown_tool_raises_with_truncated_list(self) -> None:
        tools = [f"func_{i}" for i in range(7)]
        meta = _skill_meta("weather", tools)
        with pytest.raises(FileNotFoundError) as exc:
            mcp_skill_generator.generate_tool_doc(meta, "nope")
        assert "(7 total)" in str(exc.value)

    def test_cached_tool_doc_returned(self) -> None:
        meta = _skill_meta("weather", ["get_temp"])
        assert meta.mcp is not None
        meta.mcp.tool_docs["get_temp"] = "# cached-doc"
        assert mcp_skill_generator.generate_tool_doc(meta, "get_temp") == "# cached-doc"

    def test_tool_doc_renders_template(self) -> None:
        schema: dict[str, dict[str, object]] = {
            "get_temp": {
                "description": "Get temperature",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "city": {
                            "type": "string",
                            "description": "City name",
                        }
                    },
                    "required": ["city"],
                },
            }
        }
        meta = _skill_meta("weather", ["get_temp"], schemas=schema)
        out = mcp_skill_generator.generate_tool_doc(meta, "get_temp")
        assert "get_temp" in out
        assert "weather" in out
        assert "City name" in out
        assert meta.mcp is not None
        assert "get_temp" in meta.mcp.tool_docs


class TestNaming:
    def test_safe_names_default(self) -> None:
        display, skill_name = MCPSkillGenerator._get_safe_names("my-server")
        assert display == "My Server"
        assert skill_name == "mcp_my_server_skill"

    def test_safe_names_preserves_existing_prefix(self) -> None:
        _, skill_name = MCPSkillGenerator._get_safe_names("mcp_x_skill")
        assert skill_name == "mcp_x_skill"


class TestDescriptionResolution:
    def _tool(self, name: str, description: str) -> SimpleNamespace:
        return SimpleNamespace(name=name, description=description, args_schema=None)

    def test_user_description_priority(self) -> None:
        desc = resolve_description("user desc", "instructions", [self._tool("a", "t")], "srv")
        assert desc == "user desc"

    def test_existing_trigger_phrase_is_not_duplicated(self) -> None:
        assert resolve_description("Use when checking tickets", "", [], "srv") == ("Use when checking tickets")

    def test_instructions_fallback(self) -> None:
        desc = resolve_description("", "**bold** instructions\nhere", [], "srv")
        assert "bold" in desc and "**" not in desc

    def test_tool_based_description(self) -> None:
        tools = [self._tool(f"t{i}", f"Get {i} value.") for i in range(5)]
        desc = resolve_description("", None, tools, "srv")
        assert desc.startswith("MCP srv:")
        assert "and 2 more" in desc

    def test_tool_based_description_no_descriptions(self) -> None:
        tools = [self._tool(f"t{i}", "") for i in range(3)]
        desc = build_description_from_tools(tools, "my-server")
        assert "My Server" in desc
        assert "3 tools available" in desc


class TestToolList:
    def _tool_list_meta(self, count: int, schemas: dict[str, dict[str, object]] | None = None) -> SkillMetadata:
        tools = [f"fn_{i}" for i in range(count)]
        return _skill_meta("weather", tools, schemas=schemas)

    def test_few_tools_include_params(self) -> None:
        schemas: dict[str, dict[str, object]] = {
            "fn_0": {
                "description": "Desc A",
                "inputSchema": {
                    "type": "object",
                    "properties": {"x": {"type": "string", "description": "X"}},
                    "required": ["x"],
                },
            }
        }
        meta = self._tool_list_meta(1, schemas=schemas)
        out = mcp_skill_generator.generate_skill_content(meta)
        assert "fn_0(x:string)" in out
        assert "Parameters:" not in out

    def test_many_tools_truncate_description(self) -> None:
        schemas: dict[str, dict[str, object]] = {
            f"fn_{i}": {
                "description": "word " * 200,
                "inputSchema": None,
            }
            for i in range(5)
        }
        meta = self._tool_list_meta(5, schemas=schemas)
        out = mcp_skill_generator.generate_skill_content(meta)
        assert "Parameters:" not in out

    def test_non_string_description_is_omitted(self) -> None:
        schemas: dict[str, dict[str, object]] = {"fn_0": {"description": 42, "inputSchema": None}}
        out = mcp_skill_generator.generate_skill_content(self._tool_list_meta(1, schemas=schemas))
        assert "- fn_0()" in out
        assert "42" not in out

    def test_above_budget_falls_back_to_index(self) -> None:
        count = 200
        schemas: dict[str, dict[str, object]] = {
            f"fn_{i}": {"description": "Desc", "inputSchema": {"properties": {"x": {"type": "string"}}}}
            for i in range(count)
        }
        meta = self._tool_list_meta(count, schemas=schemas)
        out = mcp_skill_generator.generate_skill_content(meta)
        assert "x:string" not in out
        assert "fn_0" in out


class TestRenderSignature:
    def test_empty_schema(self) -> None:
        assert render_signature("fn", {}) == "fn()"
        assert render_signature("fn", {"type": "object"}) == "fn()"

    def test_required_and_hints(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "City", "enum": ["bj", "sh"]},
                "days": {"type": "integer", "default": 3},
                "code": {"type": "string", "pattern": "^[0-9]+$"},
            },
            "required": ["city"],
        }
        out = render_signature("fn", schema)
        assert "city:string=bj|sh" in out
        assert "days?:integer" in out
        assert "code?:string~^[0-9]+$" in out

    def test_boolean_property_schemas_are_skipped(self) -> None:
        """JSON Schema allows ``true`` as a property schema; it carries nothing to render."""
        schema = {
            "type": "object",
            "properties": {"anything": True, "city": {"type": "string"}},
            "required": ["city"],
        }
        assert render_signature("fn", schema) == "fn(city:string)"

    def test_non_object_properties_are_ignored(self) -> None:
        assert render_signature("fn", {"properties": None}) == "fn()"
        assert render_signature("fn", {"properties": ["city"]}) == "fn()"

    def test_required_must_be_a_list_of_names(self) -> None:
        """A string ``required`` must not mark every parameter required."""
        schema = {"type": "object", "properties": {"c": {"type": "string"}}, "required": "city"}
        assert render_signature("fn", schema) == "fn(c?:string)"


class TestTextProcessing:
    def test_truncate_at_sentence_boundary(self) -> None:
        out = truncate_to_sentence("First sentence. Second", max_len=50)
        assert out == "First sentence."

    def test_truncate_at_max_len(self) -> None:
        out = truncate_to_sentence("x" * 200, max_len=150)
        assert out == "x" * 150 + "..."

    def test_truncate_short_text_unchanged(self) -> None:
        assert truncate_to_sentence("short") == "short"

    def test_clean_markdown(self) -> None:
        out = clean_markdown("## **bold** and *em*\nnext")
        assert out == "bold and em next"
        assert "**" not in out


class TestCreateSkillMetadata:
    def test_builds_metadata_with_instructions_key(self) -> None:
        gen = MCPSkillGenerator()
        tools = [SimpleNamespace(name="get_temp", description="Get temp", args_schema=None)]
        meta = gen._create_skill_metadata(
            "weather", tools, user_description="Weather skill", instructions="Handle weather"
        )
        assert meta.name == "mcp_weather_skill"
        assert meta.description == "Weather skill"
        assert meta.mcp is not None
        assert meta.mcp.server == "weather"
        assert meta.mcp.tools == ["get_temp"]
        assert "__instructions__" in meta.mcp.tool_schemas
        assert meta.mcp.tool_schemas["__instructions__"] == {"content": "Handle weather"}


class TestGenerateMetadataOnly:
    def test_empty_configs(self) -> None:
        assert asyncio.run(mcp_skill_generator.generate_metadata_only([])) == []

    def test_connect_failure_skips_server(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class _Manager:
            async def get_connection(self, _configs: list[object]) -> object:
                raise ConnectionError("down")

        async def _manager_factory() -> object:
            return _Manager()

        monkeypatch.setattr(
            "myrm_agent_harness.toolkits.mcp.connection_manager.get_mcp_connection_manager",
            _manager_factory,
        )
        cfg = SimpleNamespace(name="broken", description="")
        out = asyncio.run(mcp_skill_generator.generate_metadata_only([cfg]))
        assert out == []

    def test_no_tools_skips_server(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class _Manager:
            def __init__(self) -> None:
                self.tools_by_server: dict[str, list[object]] = {"ok": []}
                self.instructions_by_server: dict[str, str] = {}

            async def get_connection(self, _configs: list[object]) -> _Manager:
                return self

        async def _manager_factory() -> object:
            return _Manager()

        monkeypatch.setattr(
            "myrm_agent_harness.toolkits.mcp.connection_manager.get_mcp_connection_manager",
            _manager_factory,
        )
        cfg = SimpleNamespace(name="ok", description="")
        out = asyncio.run(mcp_skill_generator.generate_metadata_only([cfg]))
        assert out == []

    def test_generates_metadata_from_tools(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class _Manager:
            def __init__(self) -> None:
                self.tools_by_server: dict[str, list[object]] = {
                    "weather": [
                        SimpleNamespace(
                            name="get_temp",
                            description="Get the current temperature.",
                            args_schema=None,
                        )
                    ]
                }
                self.instructions_by_server: dict[str, str] = {}

            async def get_connection(self, _configs: list[object]) -> _Manager:
                return self

        async def _manager_factory() -> object:
            return _Manager()

        monkeypatch.setattr(
            "myrm_agent_harness.toolkits.mcp.connection_manager.get_mcp_connection_manager",
            _manager_factory,
        )
        cfg = SimpleNamespace(name="weather", description="Weather MCP")
        out = asyncio.run(mcp_skill_generator.generate_metadata_only([cfg]))
        assert len(out) == 1
        assert out[0].name == "mcp_weather_skill"
        assert out[0].description.startswith("Weather MCP")


class TestUsageTemplateShape:
    def test_template_contains_pipeline_contract(self) -> None:
        assert "from skills." in SKILL_USAGE_TEMPLATE
        assert "file_read_tool" in SKILL_USAGE_TEMPLATE
        assert "ONE `bash_code_execute_tool`" in SKILL_USAGE_TEMPLATE
        assert "/mcp/{skill_name}/<function_name>.md" in SKILL_USAGE_TEMPLATE

    def test_template_format_only_injects_skill_name(self) -> None:
        rendered = SKILL_USAGE_TEMPLATE.format(skill_name="mcp_weather_skill")
        assert "{skill_name}" not in rendered
        assert "{{skill_name}}" not in rendered
        assert "mcp_weather_skill" in rendered
        # function-name placeholders stay literal hints for the LLM to fill
        assert "<function_name>" in rendered
        assert "<func_name>" in rendered


class TestMalformedSchemas:
    """Third-party servers send malformed JSON Schema; the L3 path must never raise."""

    def test_params_section_tolerates_non_object_properties(self) -> None:
        from myrm_agent_harness.agent.skills.mcp.schema_doc_utils import build_params_section

        assert build_params_section({"properties": None}) == "## Parameters\n\nNo parameters required."
        assert build_params_section({"properties": ["city"]}) == "## Parameters\n\nNo parameters required."

    def test_params_section_ignores_string_required(self) -> None:
        from myrm_agent_harness.agent.skills.mcp.schema_doc_utils import build_params_section

        section = build_params_section({"properties": {"c": {"type": "string"}}, "required": "city"})
        assert "### c (optional)" in section
        assert "**(required)**" not in section

    def test_params_section_renders_nullable_type_without_list_repr(self) -> None:
        from myrm_agent_harness.agent.skills.mcp.schema_doc_utils import build_params_section

        section = build_params_section({"properties": {"c": {"type": ["string", "null"]}}})
        assert "- **Type**: `string`" in section
        assert "'null'" not in section

    def test_call_example_tolerates_non_object_properties(self) -> None:
        from myrm_agent_harness.agent.skills.mcp.schema_doc_utils import build_call_example

        assert build_call_example({"properties": None}) == ""
        assert build_call_example({"properties": ["city"]}) == ""
        assert build_call_example({"properties": {"c": True}}) == ""

    def test_call_example_ignores_string_required(self) -> None:
        from myrm_agent_harness.agent.skills.mcp.schema_doc_utils import build_call_example

        # "city" as a bare string must not mark the single-letter param "c" required.
        assert build_call_example({"properties": {"c": {"type": "string"}}, "required": "city"}) == ""

    def test_signature_marks_unrenderable_properties(self) -> None:
        from myrm_agent_harness.agent.skills.mcp.schema_doc_utils import render_signature

        # An empty signature would read as a zero-argument tool.
        assert render_signature("f", {"properties": {"a": True}}) == "f(…)"
        assert render_signature("f", {"properties": {"a": {"type": "string"}}, "required": ["a"]}) == "f(a:string)"


class TestSkillNameCollisions:
    """A folded name collision must rename, never drop a server."""

    def test_colliding_server_names_both_survive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class _Manager:
            def __init__(self) -> None:
                self.tools_by_server: dict[str, list[object]] = {
                    "weather": [SimpleNamespace(name="get_temp", description="temp", args_schema=None)],
                    "weather-skill": [SimpleNamespace(name="get_wind", description="wind", args_schema=None)],
                }
                self.instructions_by_server: dict[str, str] = {}

            async def get_connection(self, _configs: list[object]) -> _Manager:
                return self

        async def _manager_factory() -> object:
            return _Manager()

        monkeypatch.setattr(
            "myrm_agent_harness.toolkits.mcp.connection_manager.get_mcp_connection_manager",
            _manager_factory,
        )
        configs = [
            SimpleNamespace(name="weather", description=""),
            SimpleNamespace(name="weather-skill", description=""),
        ]
        out = asyncio.run(mcp_skill_generator.generate_metadata_only(configs))
        assert [skill.name for skill in out] == ["mcp_weather_skill", "mcp_weather_skill_2"]

    def test_l2_import_path_uses_metadata_name(self) -> None:
        meta = _skill_meta("weather-skill", ["get_wind"])
        meta.name = "mcp_weather_skill_2"
        out = mcp_skill_generator.generate_skill_content(meta)
        assert "mcp_weather_skill_2" in out
        assert "from skills.mcp_weather_skill_2" in out
        assert "mcp_weather_skill`" not in out


class TestL2Bounded:
    """Every cap is enforced, so the assembled L2 can never exceed their sum."""

    def test_verbose_instructions_and_twenty_tools_stay_bounded(self) -> None:
        from myrm_agent_harness.agent.skills.mcp.core_generator import L2_MAX_TOKENS

        tools = [f"tool_{i}" for i in range(20)]
        schemas: dict[str, dict[str, object]] = {
            name: {
                "description": "Query records and return matches.",
                "inputSchema": {
                    "properties": {f"p{j}": {"type": "string"} for j in range(6)},
                    "required": ["p0", "p1"],
                },
            }
            for name in tools
        }
        schemas["__instructions__"] = {"content": "规则。" * 2_000}
        meta = _skill_meta("verbose", tools, schemas=schemas)
        content = mcp_skill_generator.generate_skill_content(meta)
        assert get_token_count(content) <= L2_MAX_TOKENS
