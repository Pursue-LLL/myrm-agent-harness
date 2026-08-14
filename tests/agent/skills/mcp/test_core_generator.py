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
    MCPSkillGenerator,
    SKILL_USAGE_TEMPLATE,
    USAGE_GUIDE_TOOL_THRESHOLD,
    mcp_skill_generator,
)
from myrm_agent_harness.backends.skills.types import SkillMetadata
from myrm_agent_harness.backends.skills.types_requires import MCPSkillData


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

    def test_few_tools_omit_usage_guide(self) -> None:
        meta = _skill_meta("weather", ["get_temp"])
        out = mcp_skill_generator.generate_skill_content(meta)
        assert "Usage Guide" not in out
        assert "get_temp" in out

    def test_many_tools_embed_usage_guide(self) -> None:
        tools = [f"func_{i}" for i in range(USAGE_GUIDE_TOOL_THRESHOLD + 1)]
        meta = _skill_meta("weather", tools)
        out = mcp_skill_generator.generate_skill_content(meta)
        assert "Usage Guide (Must Follow)" in out
        assert "Skill Name" in out
        assert "mcp_weather_skill" in out
        for fragment in (
            "Scenario A",
            "Scenario B",
            "Scenario C",
            "[RESULT]",
            "FORBIDDEN",
            "skills.mcp_weather_skill",
            "file_read_tool",
        ):
            assert fragment in out, fragment

    def test_skill_content_cached_after_generation(self) -> None:
        tools = [f"func_{i}" for i in range(USAGE_GUIDE_TOOL_THRESHOLD + 1)]
        meta = _skill_meta("weather", tools)
        mcp_skill_generator.generate_skill_content(meta)
        assert meta.mcp is not None
        assert meta.mcp.skill_content is not None
        assert "Usage Guide" in meta.mcp.skill_content


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
        gen = MCPSkillGenerator()
        desc = gen._resolve_description(
            "user desc", "instructions", [self._tool("a", "t")], "srv"
        )
        assert desc == "user desc"

    def test_instructions_fallback(self) -> None:
        gen = MCPSkillGenerator()
        desc = gen._resolve_description(
            "", "**bold** instructions\nhere", [], "srv"
        )
        assert "bold" in desc and "**" not in desc

    def test_tool_based_description(self) -> None:
        gen = MCPSkillGenerator()
        tools = [self._tool(f"t{i}", f"Get {i} value.") for i in range(5)]
        desc = gen._resolve_description("", None, tools, "srv")
        assert desc.startswith("MCP srv:")
        assert "and 2 more" in desc

    def test_tool_based_description_no_descriptions(self) -> None:
        gen = MCPSkillGenerator()
        tools = [self._tool(f"t{i}", "") for i in range(3)]
        desc = gen._build_description_from_tools(tools, "my-server")
        assert "My Server" in desc
        assert "3 tools available" in desc


class TestToolList:
    def _tool_list_meta(
        self, count: int, schemas: dict[str, dict[str, object]] | None = None
    ) -> SkillMetadata:
        tools = [f"fn_{i}" for i in range(count)]
        return _skill_meta("weather", tools, schemas=schemas)

    def test_few_tools_include_params_and_returns(self) -> None:
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
        assert "Parameters:" in out
        assert "Returns" in out
        assert "`x`" in out

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


class TestFormatParamsInline:
    def test_empty_schema(self) -> None:
        assert MCPSkillGenerator._format_params_inline({}) == ""
        assert MCPSkillGenerator._format_params_inline({"type": "object"}) == ""
        assert MCPSkillGenerator._format_params_inline(None) == ""  # type: ignore[arg-type]

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
        out = MCPSkillGenerator._format_params_inline(schema)
        assert "`city` (string) **(required)**: City [enum: ['bj', 'sh']]" in out
        assert "default: `3`" in out
        assert "pattern: `^[0-9]+$`" in out


class TestTextProcessing:
    def test_truncate_at_sentence_boundary(self) -> None:
        out = MCPSkillGenerator._truncate_to_sentence("First sentence. Second", max_len=50)
        assert out == "First sentence."

    def test_truncate_at_max_len(self) -> None:
        out = MCPSkillGenerator._truncate_to_sentence("x" * 200, max_len=150)
        assert out == "x" * 150 + "..."

    def test_truncate_short_text_unchanged(self) -> None:
        assert MCPSkillGenerator._truncate_to_sentence("short") == "short"

    def test_clean_markdown(self) -> None:
        out = MCPSkillGenerator._clean_markdown("## **bold** and *em*\nnext")
        assert out == "bold and em next"
        assert "**" not in out


class TestCreateSkillMetadata:
    def test_builds_metadata_with_instructions_key(self) -> None:
        gen = MCPSkillGenerator()
        tools = [
            SimpleNamespace(name="get_temp", description="Get temp", args_schema=None)
        ]
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

            async def get_connection(self, _configs: list[object]) -> "_Manager":
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

            async def get_connection(self, _configs: list[object]) -> "_Manager":
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
        assert out[0].description == "Weather MCP"


class TestUsageTemplateShape:
    def test_template_contains_pipeline_contract(self) -> None:
        assert "Step 1" in SKILL_USAGE_TEMPLATE
        assert "Step 2" in SKILL_USAGE_TEMPLATE
        assert "skills." in SKILL_USAGE_TEMPLATE
        assert "file_read_tool" in SKILL_USAGE_TEMPLATE

    def test_template_format_only_injects_skill_name(self) -> None:
        rendered = SKILL_USAGE_TEMPLATE.format(skill_name="mcp_weather_skill")
        assert "{skill_name}" not in rendered
        assert "{{skill_name}}" not in rendered
        assert "mcp_weather_skill" in rendered
        # function-name placeholders stay literal hints for the LLM to fill
        assert "<function_name>" in rendered
        assert "<func_name>" in rendered
