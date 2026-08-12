"""End-to-end tests for property-key sanitization in the MCP tool pipeline.

Simulates the Cloudflare flat API scenario: an MCP tool ships non-conforming
property keys (``issue_class~neq``, ``meta.<field>[<operator>]``). After
``sanitize_tools`` the LLM-facing schema must carry only conforming keys and
the dispatch wrapper must restore the original wire names before the tool
coroutine runs.
"""

import json

import pytest
from langchain_core.tools import StructuredTool

from myrm_agent_harness.toolkits.mcp.schema.key_sanitize import sanitize_property_keys
from myrm_agent_harness.toolkits.mcp.tool_processing import sanitize_tools


class TestSanitizeToolsKeyRenaming:
    """sanitize_tools pipeline: rename -> flatten -> dispatch restore."""

    @pytest.mark.asyncio
    async def test_cloudflare_flat_api_roundtrip(self):
        seen: dict = {}

        async def _capture(**kwargs):
            seen.update(kwargs)
            return "ok"

        tool = StructuredTool(
            name="list_issues",
            description="query",
            args_schema={
                "type": "object",
                "properties": {
                    "issue_class~neq": {"type": "string"},
                    "meta.<status>[eq]": {"type": "string"},
                    "page": {"type": "integer"},
                },
                "required": ["issue_class~neq", "page"],
            },
            coroutine=_capture,
        )

        sanitize_tools([tool])

        schema = tool.args_schema
        props = schema["properties"]
        # No raw bad keys may leak into the LLM-facing schema.
        assert "issue_class~neq" not in props
        assert "meta.<status>[eq]" not in props
        assert "page" in props
        assert schema["required"] == ["issue_class_neq", "page"]

        # The restore map rides on tool metadata.
        assert tool.metadata["_key_restore_map"] == {
            "issue_class_neq": "issue_class~neq",
            "meta__status__eq": "meta.<status>[eq]",
        }

        # Model emits conforming (renamed) keys — wire names restored at dispatch.
        result = await tool.coroutine(
            issue_class_neq="open",
            meta__status__eq="assigned",
            page=2,
        )
        assert result == "ok"
        assert seen == {
            "issue_class~neq": "open",
            "meta.<status>[eq]": "assigned",
            "page": 2,
        }

    @pytest.mark.asyncio
    async def test_no_renames_does_not_attach_metadata(self):
        seen: dict = {}

        async def _capture(**kwargs):
            seen.update(kwargs)
            return "ok"

        tool = StructuredTool(
            name="simple",
            description="d",
            args_schema={
                "type": "object",
                "properties": {"a": {"type": "string"}, "b": {"type": "integer"}},
            },
            coroutine=_capture,
        )

        sanitize_tools([tool])

        assert "_key_restore_map" not in (tool.metadata or {})
        await tool.coroutine(a="x", b=1)
        assert seen == {"a": "x", "b": 1}

    def test_sanitize_property_keys_stores_collision_safe_restore(self):
        """Collision handling stays deterministic end to end."""
        schema = {
            "type": "object",
            "properties": {"a.b": {"type": "string"}, "a_b": {"type": "integer"}},
            "required": ["a.b"],
        }
        result, restore_map = sanitize_property_keys(schema)
        assert result["properties"]["a_b_2"]["type"] == "string"
        assert result["required"] == ["a_b_2"]
        assert restore_map == {"a_b_2": "a.b"}


class TestRestoreWireNamesAtDispatch:
    """The dispatch wrapper restores wire names for nested arguments."""

    @pytest.mark.asyncio
    async def test_nested_renamed_keys_restored(self):
        seen: dict = {}

        async def _capture(**kwargs):
            seen.update(kwargs)
            return "ok"

        tool = StructuredTool(
            name="nested",
            description="d",
            args_schema={
                "type": "object",
                "properties": {
                    "filters": {
                        "type": "object",
                        "properties": {"op[is]": {"type": "string"}},
                    }
                },
            },
            coroutine=_capture,
        )

        sanitize_tools([tool])

        await tool.coroutine(filters={"op_is": "eq"})
        assert seen == {"filters": {"op[is]": "eq"}}

    @pytest.mark.asyncio
    async def test_schema_remains_valid_json(self):
        """The renamed schema stays serializable (strict provider contract)."""

        async def _capture(**kwargs):
            return "ok"

        tool = StructuredTool(
            name="weird",
            description="d",
            args_schema={
                "type": "object",
                "properties": {
                    "名前": {"type": "string"},
                    "ok": {"type": "string"},
                },
            },
            coroutine=_capture,
        )

        sanitize_tools([tool])
        # A provider-side JSON round trip must succeed and keep keys conforming.
        dumped = json.dumps(tool.args_schema)
        assert "名前" not in dumped
        assert "param" in dumped
