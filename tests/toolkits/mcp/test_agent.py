import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.tools import StructuredTool
from mcp.types import (
    CallToolResult,
    ImageContent,
    ResourceLink,
    TextContent,
)

from myrm_agent_harness.toolkits.mcp.agent import MCPAgent
from myrm_agent_harness.toolkits.mcp.result_processing import (
    coerce_content_block,
    emit_mcp_app_event,
    extract_mcp_app_metadata,
    normalize_mcp_result,
)
from myrm_agent_harness.toolkits.mcp.tool_processing import (
    apply_tool_filter,
    enforce_description_limits,
    prefix_tool_names,
    register_tool_annotations,
    sanitize_tools,
    wrap_tools_with_timeout,
)


class DummyConfig:
    """Minimal config satisfying MCPServerConfigProtocol (structural typing)."""

    name: str = "test_server"
    type: str = "stdio"
    url: str | None = None
    command: str | None = "python"
    args: list[str] | None = ["-m", "mcp_server"]  # noqa: RUF012
    description: str = "test"
    headers: dict[str, str] | None = None
    extra_params: dict[str, object] | None = None
    required_secrets: list[str] | None = None
    tool_include: list[str] | None = None
    tool_exclude: list[str] | None = None
    host_serial: bool = False
    connect_timeout: float = 1.0
    execute_timeout: float = 2.0
    keepalive_interval: float | None = None
    ssl_verify: bool | str | None = None
    client_cert: str | None = None
    client_key: str | None = None
    client_key_password: str | None = None


def _make_tool(
    name: str = "test_tool",
    description: str = "a test tool",
    schema: dict[str, Any] | None = None,
    coroutine: Any = None,
    metadata: dict[str, Any] | None = None,
) -> StructuredTool:
    tool = StructuredTool(
        name=name,
        description=description,
        args_schema=schema
        or {"type": "object", "properties": {"a": {"type": "string"}}},
        coroutine=coroutine or AsyncMock(return_value="ok"),
    )
    if metadata:
        tool.metadata = metadata
    return tool


def _patch_enumerate(
    agent: MCPAgent, tools_by_server: dict[str, list[StructuredTool] | Exception]
):
    """Patch _enumerate_server_tools to return pre-built tools by server name."""

    async def _fake_enumerate(server_config):
        name = server_config.name
        result = tools_by_server.get(name)
        if isinstance(result, Exception):
            raise result
        tools = result if result is not None else []
        return (name, tools, None if tools else "not found tools")

    return patch.object(agent, "_enumerate_server_tools", side_effect=_fake_enumerate)


# ---------------------------------------------------------------------------
# Core workflow: single-server get_tools
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_tools_single_server():
    agent = MCPAgent()
    config = DummyConfig()

    with _patch_enumerate(agent, {"test_server": [_make_tool()]}):
        tools = await agent.get_tools([config])

    assert len(tools) == 1
    assert tools[0].name == "mcp__test_server__test_tool"
    assert hasattr(tools[0], "args_schema")


# ---------------------------------------------------------------------------
# get_tools() with None config returns empty
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_tools_none_config():
    agent = MCPAgent()
    tools = await agent.get_tools(None)
    assert tools == []


# ---------------------------------------------------------------------------
# get_tools() with empty config returns empty
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_tools_empty_config():
    agent = MCPAgent()
    tools = await agent.get_tools([])
    assert tools == []


# ---------------------------------------------------------------------------
# Connection timeout handling via _enumerate_server_tools
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_enumerate_server_tools_connection_timeout():
    agent = MCPAgent()
    config = DummyConfig()
    config.connect_timeout = 0.1

    async def slow_list(*_a, **_k):
        await asyncio.sleep(0.5)
        return []

    mock_aexit = AsyncMock(return_value=False)
    with (
        patch("myrm_agent_harness.toolkits.mcp.agent._TOOL_FETCH_RETRY_BACKOFF", 0),
        patch.object(MCPAgent, "_build_enumeration_target", return_value="http://mock"),
        patch("mcp.client.Client.__aenter__", new_callable=AsyncMock) as mock_enter,
        patch("mcp.client.Client.__aexit__", mock_aexit),
        patch("mcp.client.Client.list_tools", side_effect=slow_list),
    ):
        mock_enter.return_value = MagicMock()
        _server_name, tools, err = await agent._enumerate_server_tools(config)

    assert err is not None
    assert "connection timed out" in err
    assert tools == []


# ---------------------------------------------------------------------------
# Empty tool list from server
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_enumerate_server_tools_empty_tools():
    agent = MCPAgent()
    config = DummyConfig()
    config.name = "empty_server"

    with _patch_enumerate(agent, {"empty_server": []}):
        server_name, tools, err = await agent._enumerate_server_tools(config)

    assert server_name == "empty_server"
    assert tools == []
    assert err == "not found tools"


# ---------------------------------------------------------------------------
# Bounded retry recovers a transient empty/failed enumeration
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_enumerate_server_tools_retry_then_succeeds():
    from types import SimpleNamespace

    agent = MCPAgent()
    config = DummyConfig()
    config.name = "flaky_server"
    attempts = {"n": 0}

    mock_tool = SimpleNamespace(
        name="recovered_tool",
        description="a tool",
        input_schema={"type": "object", "properties": {}},
    )

    async def _fake_list_tools():
        attempts["n"] += 1
        if attempts["n"] == 1:
            return SimpleNamespace(tools=[])
        return SimpleNamespace(tools=[mock_tool])

    mock_client = MagicMock()
    mock_client.list_tools = _fake_list_tools
    mock_client.call_tool = AsyncMock(return_value=SimpleNamespace(content=[]))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    mock_client_cls = MagicMock(return_value=mock_client)

    with (
        patch("mcp.client.Client", mock_client_cls),
        patch.object(agent, "_build_enumeration_target", return_value=MagicMock()),
        patch("myrm_agent_harness.toolkits.mcp.agent._TOOL_FETCH_RETRY_BACKOFF", 0),
    ):
        _, tools, err = await agent._enumerate_server_tools(config)

    assert err is None
    assert len(tools) == 1
    assert attempts["n"] == 2


# ---------------------------------------------------------------------------
# Generic exception in _enumerate_server_tools
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_enumerate_server_tools_generic_exception():
    agent = MCPAgent()
    config = DummyConfig()
    config.name = "bad_server"

    async def _fake_enumerate(server_config):
        return ("bad_server", [], "network error")

    with patch.object(agent, "_enumerate_server_tools", side_effect=_fake_enumerate):
        server_name, tools, err = await agent._enumerate_server_tools(config)

    assert server_name == "bad_server"
    assert tools == []
    assert "network error" in err


# ---------------------------------------------------------------------------
# CancelledError handling in _enumerate_server_tools
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_enumerate_server_tools_cancelled_error():
    agent = MCPAgent()
    config = DummyConfig()
    config.name = "cancel_server"

    async def _fake_enumerate(server_config):
        return ("cancel_server", [], "cancelled by SDK")

    with patch.object(agent, "_enumerate_server_tools", side_effect=_fake_enumerate):
        server_name, tools, err = await agent._enumerate_server_tools(config)

    assert server_name == "cancel_server"
    assert tools == []
    assert err == "cancelled by SDK"


# ---------------------------------------------------------------------------
# Single server error raises in get_tools
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_tools_single_server_error():
    agent = MCPAgent()
    config = DummyConfig()
    config.name = "fail_server"

    with (
        _patch_enumerate(agent, {"fail_server": []}),
        pytest.raises(RuntimeError, match="Failed to get tools from fail_server"),
    ):
        await agent.get_tools([config])


# ---------------------------------------------------------------------------
# Multi-server parallel fetch
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_tools_parallel_multi_server():
    agent = MCPAgent()
    cfg1 = DummyConfig()
    cfg1.name = "server1"
    cfg2 = DummyConfig()
    cfg2.name = "server2"

    big_tool = _make_tool(
        name="tool_multi", description="A" * 3000, schema={"type": "object"}
    )
    with _patch_enumerate(
        agent,
        {
            "server1": [big_tool],
            "server2": [_make_tool(name="tool_multi", description="A" * 3000)],
        },
    ):
        tools = await agent.get_tools([cfg1, cfg2])

    assert len(tools) == 2
    assert len(tools[0].description) == 2051


# ---------------------------------------------------------------------------
# Multi-server: task exception propagation
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_tools_parallel_task_exception():
    agent = MCPAgent()
    cfg1 = DummyConfig()
    cfg1.name = "s1"
    cfg2 = DummyConfig()
    cfg2.name = "s2"

    async def _explode(_cfg):
        raise RuntimeError("boom")

    with (
        patch.object(agent, "_enumerate_server_tools", side_effect=_explode),
        pytest.raises(RuntimeError, match="boom"),
    ):
        await agent.get_tools([cfg1, cfg2])


# ---------------------------------------------------------------------------
# Multi-server: error in one server propagates
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_tools_parallel_server_error():
    agent = MCPAgent()
    cfg_ok = DummyConfig()
    cfg_ok.name = "ok_server"
    cfg_err = DummyConfig()
    cfg_err.name = "err_server"

    with (
        _patch_enumerate(agent, {"ok_server": [_make_tool()], "err_server": []}),
        pytest.raises(RuntimeError, match="Failed to get tools"),
    ):
        await agent.get_tools([cfg_ok, cfg_err])


# ---------------------------------------------------------------------------
# Tool server mapping lookup
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_tool_server_mapping():
    agent = MCPAgent()
    config = DummyConfig()

    with _patch_enumerate(agent, {"test_server": [_make_tool()]}):
        tools = await agent.get_tools([config])

    assert agent.get_tool_server_name(tools[0]) == "test_server"
    assert (
        agent.get_server_name_by_tool_name("mcp__test_server__test_tool")
        == "test_server"
    )
    assert agent.get_server_name_by_tool_name("nonexistent") == "unknown_server"


# ---------------------------------------------------------------------------
# _wrap_tools_with_timeout: skips tools without coroutine (covers line 91)
# ---------------------------------------------------------------------------
def test_wrap_tools_with_timeout_no_coroutine():
    tool = MagicMock()
    tool.coroutine = None
    wrap_tools_with_timeout([tool], 10.0)
    assert tool.coroutine is None


# ---------------------------------------------------------------------------
# _wrap_tools_with_timeout: timeout fires (covers line 102-108)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_wrap_tools_timeout_fires():
    async def slow_fn(*_a, **_kw):
        await asyncio.sleep(5)

    tool = _make_tool(coroutine=slow_fn)
    wrap_tools_with_timeout([tool], timeout=0.05)

    result = await tool.coroutine()
    assert "timed out" in result


# ---------------------------------------------------------------------------
# _wrap_tools_with_timeout: normal execution (covers line 102-104)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_wrap_tools_normal_execution():
    async def fast_fn(*_a, **_kw):
        return "success"

    tool = _make_tool(coroutine=fast_fn)
    wrap_tools_with_timeout([tool], timeout=5.0)

    result = await tool.coroutine()
    assert "success" in result
    assert "UNTRUSTED_DATA" in result


# ---------------------------------------------------------------------------
# _wrap_tools_with_timeout: output size guard (max_output_chars truncation)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_wrap_tools_output_guard_no_truncation():
    """Output within limit passes through unchanged."""
    async def small_output(*_a, **_kw):
        return "short result"

    tool = _make_tool(coroutine=small_output)
    wrap_tools_with_timeout([tool], timeout=5.0, max_output_chars=1000)

    result = await tool.coroutine()
    assert "short result" in result
    assert "UNTRUSTED_DATA" in result


@pytest.mark.asyncio
async def test_wrap_tools_output_guard_truncates_large_output():
    """Output exceeding max_output_chars is truncated with notice."""
    large_text = "x" * 500

    async def large_output(*_a, **_kw):
        return large_text

    tool = _make_tool(coroutine=large_output)
    wrap_tools_with_timeout([tool], timeout=5.0, max_output_chars=100)

    result = await tool.coroutine()
    assert isinstance(result, str)
    assert "x" * 100 in result
    assert "[Output truncated:" in result
    assert "showing first 100 of 500 chars" in result
    assert "Remaining 400 chars were discarded" in result
    assert "UNTRUSTED_DATA" in result


@pytest.mark.asyncio
async def test_wrap_tools_output_guard_truncates_multimodal_text_blocks():
    """Multimodal oversized text blocks are truncated; image blocks are kept."""
    raw_result = CallToolResult(
        content=[
            ImageContent(type="image", data="abc123", mime_type="image/png"),
            TextContent(type="text", text="x" * 500),
        ]
    )

    async def image_output(*_a, **_kw):
        return raw_result

    tool = _make_tool(coroutine=image_output)
    wrap_tools_with_timeout([tool], timeout=5.0, max_output_chars=100)

    result = await tool.coroutine()
    assert isinstance(result, list)
    assert len(result) == 2
    assert result[0]["type"] == "image"
    text_block = result[1]
    assert text_block["type"] == "text"
    assert "x" * 100 in text_block["text"]
    assert "[Output truncated:" in text_block["text"]
    assert "showing first 100 of 500 chars" in text_block["text"]
    assert "Remaining 400 chars were discarded" in text_block["text"]
    assert "UNTRUSTED_DATA" in text_block["text"]


@pytest.mark.asyncio
async def test_wrap_tools_output_guard_exact_boundary():
    """Output exactly at limit should NOT be truncated."""
    exact_text = "y" * 1000

    async def exact_output(*_a, **_kw):
        return exact_text

    tool = _make_tool(coroutine=exact_output)
    wrap_tools_with_timeout([tool], timeout=5.0, max_output_chars=1000)

    result = await tool.coroutine()
    assert exact_text in result
    assert "UNTRUSTED_DATA" in result
    assert "[Output truncated:" not in result


@pytest.mark.asyncio
async def test_wrap_tools_output_guard_empty_string():
    """Empty string output passes through without truncation."""
    async def empty_output(*_a, **_kw):
        return ""

    tool = _make_tool(coroutine=empty_output)
    wrap_tools_with_timeout([tool], timeout=5.0, max_output_chars=1000)

    result = await tool.coroutine()
    assert result == ""


@pytest.mark.asyncio
async def test_wrap_tools_output_guard_text_tuple_truncated():
    """Text-only CallToolResult (normalized to str) is truncated when oversized."""
    large_text = "z" * 300

    async def text_output(*_a, **_kw):
        return CallToolResult(content=[TextContent(type="text", text=large_text)])

    tool = _make_tool(coroutine=text_output)
    wrap_tools_with_timeout([tool], timeout=5.0, max_output_chars=50)

    result = await tool.coroutine()
    assert isinstance(result, str)
    assert "z" * 50 in result
    assert "[Output truncated:" in result
    assert "showing first 50 of 300 chars" in result
    assert "UNTRUSTED_DATA" in result


@pytest.mark.asyncio
async def test_wrap_tools_output_guard_one_char_over():
    """Output 1 char over the limit should still be truncated."""
    text = "a" * 1001

    async def over_by_one(*_a, **_kw):
        return text

    tool = _make_tool(coroutine=over_by_one)
    wrap_tools_with_timeout([tool], timeout=5.0, max_output_chars=1000)

    result = await tool.coroutine()
    assert "[Output truncated:" in result
    assert "showing first 1,000 of 1,001 chars" in result
    assert "Remaining 1 chars were discarded" in result


# ---------------------------------------------------------------------------
# _sanitize_tools: coercion wrapper (covers line 150-154)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_sanitize_tools_coercion():
    inner_mock = AsyncMock(return_value="coerced_result")
    tool = _make_tool(
        schema={"type": "object", "properties": {"count": {"type": "integer"}}},
        coroutine=inner_mock,
    )
    sanitize_tools([tool])
    result = await tool.coroutine(count="42")
    assert result == "coerced_result"
    inner_mock.assert_called_once()


@pytest.mark.asyncio
async def test_sanitize_tools_strict_host_required_nullable_contract():
    """End-to-end strict-host contract: missing required+nullable args are completed."""
    inner_mock = AsyncMock(return_value="strict_ok")
    strict_schema = {
        "type": "object",
        "properties": {
            "captureTransform": {"type": ["object", "null"]},
            "annotations": {"type": ["object", "null"]},
            "bShowUI": {"type": "boolean"},
        },
        "required": ["captureTransform", "annotations", "bShowUI"],
    }
    tool = _make_tool(schema=strict_schema, coroutine=inner_mock)
    sanitize_tools([tool])

    result = await tool.coroutine(bShowUI="false")
    assert result == "strict_ok"
    call_kwargs = inner_mock.call_args[1]
    assert call_kwargs["bShowUI"] is False
    assert call_kwargs["captureTransform"] is None
    assert call_kwargs["annotations"] is None


@pytest.mark.asyncio
async def test_sanitize_tools_nullable_true_contract():
    """OpenAPI nullable:true must be treated as explicit null-allowed."""
    inner_mock = AsyncMock(return_value="nullable_flag_ok")
    schema = {
        "type": "object",
        "properties": {
            "opt": {"type": "object", "nullable": True},
            "name": {"type": "string"},
        },
        "required": ["opt", "name"],
    }
    tool = _make_tool(schema=schema, coroutine=inner_mock)
    sanitize_tools([tool])

    result = await tool.coroutine(name="demo")
    assert result == "nullable_flag_ok"
    call_kwargs = inner_mock.call_args[1]
    assert call_kwargs["name"] == "demo"
    assert call_kwargs["opt"] is None


@pytest.mark.asyncio
async def test_sanitize_tools_anyof_enum_null_contract():
    """Null-literal enum branches in anyOf must permit explicit null completion."""
    inner_mock = AsyncMock(return_value="enum_null_ok")
    schema = {
        "type": "object",
        "properties": {
            "opt": {
                "anyOf": [
                    {"type": "object"},
                    {"enum": [None]},
                ]
            },
            "name": {"type": "string"},
        },
        "required": ["opt", "name"],
    }
    tool = _make_tool(schema=schema, coroutine=inner_mock)
    sanitize_tools([tool])

    result = await tool.coroutine(name="demo")
    assert result == "enum_null_ok"
    call_kwargs = inner_mock.call_args[1]
    assert call_kwargs["name"] == "demo"
    assert call_kwargs["opt"] is None


@pytest.mark.asyncio
async def test_sanitize_tools_mixed_union_prefers_container_literal():
    """Mixed unions should parse JSON object literals when schema accepts object."""
    inner_mock = AsyncMock(return_value="mixed_union_ok")
    schema = {
        "type": "object",
        "properties": {
            "payload": {
                "anyOf": [
                    {"type": "string"},
                    {"type": "object"},
                    {"type": "null"},
                ]
            }
        },
    }
    tool = _make_tool(schema=schema, coroutine=inner_mock)
    sanitize_tools([tool])

    result = await tool.coroutine(payload='{"x": 1}')
    assert result == "mixed_union_ok"
    call_kwargs = inner_mock.call_args[1]
    assert call_kwargs["payload"] == {"x": 1}


@pytest.mark.asyncio
async def test_sanitize_tools_mixed_union_keeps_plain_string():
    """Mixed unions should preserve plain text payloads as strings."""
    inner_mock = AsyncMock(return_value="mixed_union_string_ok")
    schema = {
        "type": "object",
        "properties": {
            "payload": {
                "anyOf": [
                    {"type": "string"},
                    {"type": "object"},
                    {"type": "null"},
                ]
            }
        },
    }
    tool = _make_tool(schema=schema, coroutine=inner_mock)
    sanitize_tools([tool])

    result = await tool.coroutine(payload="hello world")
    assert result == "mixed_union_string_ok"
    call_kwargs = inner_mock.call_args[1]
    assert call_kwargs["payload"] == "hello world"


# ---------------------------------------------------------------------------
# _sanitize_tools: canonicalize sorts schema keys in full pipeline
# ---------------------------------------------------------------------------
def test_sanitize_tools_canonicalizes_schema_keys():
    """Verify that _sanitize_tools produces deterministic key ordering
    regardless of the original key order from MCP server."""
    schema_shuffled: dict[str, Any] = {
        "required": ["z_param", "a_param"],
        "type": "object",
        "properties": {
            "z_param": {"type": "string", "description": "last"},
            "a_param": {"type": "integer", "description": "first"},
        },
    }
    tool = _make_tool(schema=schema_shuffled)
    sanitize_tools([tool])

    result_schema = tool.args_schema
    assert list(result_schema.keys()) == ["properties", "required", "type"]
    assert list(result_schema["properties"].keys()) == ["a_param", "z_param"]
    assert result_schema["required"] == ["a_param", "z_param"]
    inner_a = result_schema["properties"]["a_param"]
    assert list(inner_a.keys()) == ["description", "type"]


# ---------------------------------------------------------------------------
# _sanitize_tools: two schemas with different key orders produce same result
# ---------------------------------------------------------------------------
def test_sanitize_tools_deterministic_across_restarts():
    """Simulate MCP server restart returning same schema with different key order.
    After _sanitize_tools, both must serialize identically (cache-stable)."""
    import json as _json

    schema_v1: dict[str, Any] = {
        "type": "object",
        "properties": {"repo": {"type": "string"}, "branch": {"type": "string"}},
        "required": ["repo", "branch"],
    }
    schema_v2: dict[str, Any] = {
        "required": ["branch", "repo"],
        "properties": {"branch": {"type": "string"}, "repo": {"type": "string"}},
        "type": "object",
    }
    tool1 = _make_tool(name="git_clone", schema=schema_v1)
    tool2 = _make_tool(name="git_clone", schema=schema_v2)
    sanitize_tools([tool1])
    sanitize_tools([tool2])

    assert _json.dumps(tool1.args_schema) == _json.dumps(tool2.args_schema)


# ---------------------------------------------------------------------------
# _register_tool_annotations: extracts MCP annotations (covers line 178)
# ---------------------------------------------------------------------------
def test_register_tool_annotations():
    tool = _make_tool(
        metadata={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        }
    )

    with patch(
        "myrm_agent_harness.toolkits.mcp.tool_processing.register_ptc_safety_metadata"
    ) as mock_reg:
        register_tool_annotations([tool], "my-server")

    mock_reg.assert_called_once()
    call_args = mock_reg.call_args
    assert call_args[0][0] == "mcp_my_server_skill"
    assert call_args[0][1] == "test_tool"
    safety = call_args[0][2]
    assert safety.is_read_only is True
    assert safety.is_concurrent_safe is True
    assert safety.is_destructive is False
    assert safety.is_idempotent is True


def test_register_tool_annotations_host_serial_forces_non_concurrent():
    tool = _make_tool(
        metadata={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        }
    )

    with patch(
        "myrm_agent_harness.toolkits.mcp.tool_processing.register_ptc_safety_metadata"
    ) as mock_reg:
        register_tool_annotations([tool], "my-server", host_serial=True)

    safety = mock_reg.call_args[0][2]
    assert safety.is_read_only is True
    assert safety.is_concurrent_safe is False


# ---------------------------------------------------------------------------
# _register_tool_annotations: server name normalization
# ---------------------------------------------------------------------------
def test_register_tool_annotations_name_normalization():
    tool = _make_tool(metadata={})

    with patch(
        "myrm_agent_harness.toolkits.mcp.tool_processing.register_ptc_safety_metadata"
    ) as mock_reg:
        register_tool_annotations([tool], "mcp_already_skill")

    assert mock_reg.call_args[0][0] == "mcp_already_skill"


def test_register_tool_annotations_plain_name():
    tool = _make_tool(metadata={})

    with patch(
        "myrm_agent_harness.toolkits.mcp.tool_processing.register_ptc_safety_metadata"
    ) as mock_reg:
        register_tool_annotations([tool], "github")

    assert mock_reg.call_args[0][0] == "mcp_github_skill"


# ---------------------------------------------------------------------------
# Description truncation boundary
# ---------------------------------------------------------------------------
def test_enforce_description_limits_no_truncation():
    tool = _make_tool(description="short")
    enforce_description_limits([tool])
    assert tool.description == "short"


def test_enforce_description_limits_exact_boundary():
    tool = _make_tool(description="x" * 2048)
    enforce_description_limits([tool])
    assert len(tool.description) == 2048


def test_enforce_description_limits_truncates():
    tool = _make_tool(description="x" * 3000)
    enforce_description_limits([tool])
    assert len(tool.description) == 2051
    assert tool.description.endswith("...")


# ---------------------------------------------------------------------------
# _sanitize_tools: nested arg restoration via dot-keys (covers line 153)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_sanitize_tools_flattened_dot_keys():
    """When schema exceeds depth threshold, flatten_deep_schema activates.
    The coercion wrapper must then restore nested structure from dot-path keys."""
    inner_mock = AsyncMock(return_value="nested_ok")
    deep_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "level1": {
                "type": "object",
                "properties": {
                    "level2": {
                        "type": "object",
                        "properties": {
                            "value": {"type": "string"},
                        },
                    },
                },
            },
        },
    }
    tool = _make_tool(schema=deep_schema, coroutine=inner_mock)
    sanitize_tools([tool])

    result = await tool.coroutine(**{"level1.level2.value": "deep"})
    assert result == "nested_ok"
    call_kwargs = inner_mock.call_args[1]
    assert "level1" in call_kwargs
    assert call_kwargs["level1"]["level2"]["value"] == "deep"


# ---------------------------------------------------------------------------
# Multi-server: gather returns Exception object
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_tools_parallel_gather_exception_object():
    """When asyncio.gather(return_exceptions=True) returns an Exception
    object (not a tuple), it must be raised."""
    agent = MCPAgent()
    cfg1 = DummyConfig()
    cfg1.name = "s1"
    cfg2 = DummyConfig()
    cfg2.name = "s2"

    call_count = 0

    async def _explode_on_second(cfg):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return ("s1", [_make_tool()], None)
        raise RuntimeError("gather_boom")

    with (
        patch.object(agent, "_enumerate_server_tools", side_effect=_explode_on_second),
        pytest.raises(RuntimeError, match="gather_boom"),
    ):
        await agent.get_tools([cfg1, cfg2])


# ---------------------------------------------------------------------------
# _apply_tool_filter: unit tests
# ---------------------------------------------------------------------------
class TestApplyToolFilter:
    def test_no_filter_returns_all(self) -> None:
        tools = [_make_tool(name="a"), _make_tool(name="b")]
        result = apply_tool_filter(tools, "srv", None, None)
        assert len(result) == 2

    def test_empty_lists_return_all(self) -> None:
        tools = [_make_tool(name="a"), _make_tool(name="b")]
        result = apply_tool_filter(tools, "srv", [], [])
        assert len(result) == 2

    def test_include_filters(self) -> None:
        tools = [
            _make_tool(name="read"),
            _make_tool(name="write"),
            _make_tool(name="delete"),
        ]
        result = apply_tool_filter(tools, "srv", ["read", "write"], None)
        assert [t.name for t in result] == ["read", "write"]

    def test_exclude_filters(self) -> None:
        tools = [
            _make_tool(name="read"),
            _make_tool(name="write"),
            _make_tool(name="delete"),
        ]
        result = apply_tool_filter(tools, "srv", None, ["delete"])
        assert [t.name for t in result] == ["read", "write"]

    def test_include_takes_precedence(self) -> None:
        tools = [
            _make_tool(name="read"),
            _make_tool(name="write"),
            _make_tool(name="delete"),
        ]
        result = apply_tool_filter(tools, "srv", ["read"], ["write"])
        assert [t.name for t in result] == ["read"]

    def test_include_all_removed(self) -> None:
        tools = [_make_tool(name="a"), _make_tool(name="b")]
        result = apply_tool_filter(tools, "srv", ["nonexistent"], None)
        assert result == []

    def test_exclude_all_removed(self) -> None:
        tools = [_make_tool(name="a"), _make_tool(name="b")]
        result = apply_tool_filter(tools, "srv", None, ["a", "b"])
        assert result == []


# ---------------------------------------------------------------------------
# End-to-end: tool_include config filters tools in get_tools
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_tools_applies_tool_filter():
    agent = MCPAgent()
    config = DummyConfig()
    config.tool_include = ["wanted_tool"]

    with _patch_enumerate(
        agent,
        {
            "test_server": [
                _make_tool(name="wanted_tool"),
                _make_tool(name="unwanted_tool"),
            ]
        },
    ):
        tools = await agent.get_tools([config])

    assert len(tools) == 1
    assert tools[0].name == "mcp__test_server__wanted_tool"


# ---------------------------------------------------------------------------
# _prefix_tool_names: unit tests
# ---------------------------------------------------------------------------
class TestPrefixToolNames:
    def test_basic_prefix(self) -> None:
        tools = [_make_tool(name="search"), _make_tool(name="create")]
        prefix_tool_names(tools, "github")
        assert [t.name for t in tools] == ["mcp__github__search", "mcp__github__create"]

    def test_special_chars_sanitized(self) -> None:
        tools = [_make_tool(name="my-tool")]
        prefix_tool_names(tools, "my-server")
        assert tools[0].name == "mcp__my_server__my_tool"

    def test_multiple_servers_no_collision(self) -> None:
        github_tools = [_make_tool(name="search_repos")]
        gitlab_tools = [_make_tool(name="search_repos")]
        prefix_tool_names(github_tools, "github")
        prefix_tool_names(gitlab_tools, "gitlab")
        assert github_tools[0].name == "mcp__github__search_repos"
        assert gitlab_tools[0].name == "mcp__gitlab__search_repos"
        assert github_tools[0].name != gitlab_tools[0].name

    def test_process_session_tools_applies_prefix(self) -> None:
        tools = [_make_tool(name="read"), _make_tool(name="write")]
        result = MCPAgent.process_session_tools(
            tools,
            "my_server",
            None,
            None,
            10.0,
        )
        assert [t.name for t in result] == [
            "mcp__my_server__read",
            "mcp__my_server__write",
        ]

    def test_filter_uses_original_names(self) -> None:
        """tool_include uses original names (before prefixing)."""
        tools = [_make_tool(name="read"), _make_tool(name="write")]
        result = MCPAgent.process_session_tools(
            tools,
            "srv",
            ["read"],
            None,
            10.0,
        )
        assert len(result) == 1
        assert result[0].name == "mcp__srv__read"

    def test_builtin_name_collision_avoided(self) -> None:
        """An MCP tool named 'file_read_tool' gets prefixed, no collision."""
        tools = [_make_tool(name="file_read_tool")]
        result = MCPAgent.process_session_tools(
            tools,
            "remote",
            None,
            None,
            10.0,
        )
        assert result[0].name == "mcp__remote__file_read_tool"

    def test_double_underscore_eliminates_ambiguity(self) -> None:
        """server 'github_actions' + tool 'run' differs from server 'github' + tool 'actions_run'."""
        tools_a = [_make_tool(name="run")]
        tools_b = [_make_tool(name="actions_run")]
        prefix_tool_names(tools_a, "github_actions")
        prefix_tool_names(tools_b, "github")
        assert tools_a[0].name == "mcp__github_actions__run"
        assert tools_b[0].name == "mcp__github__actions_run"
        assert tools_a[0].name != tools_b[0].name

    def test_server_name_with_consecutive_hyphens(self) -> None:
        """Consecutive hyphens collapse to single underscore after sanitize."""
        tools = [_make_tool(name="echo")]
        prefix_tool_names(tools, "my--server")
        assert tools[0].name == "mcp__my_server__echo"

    def test_unicode_server_name(self) -> None:
        """Non-ASCII characters sanitized to underscores."""
        tools = [_make_tool(name="list")]
        prefix_tool_names(tools, "飞书mcp")
        assert tools[0].name == "mcp__mcp__list"

    def test_roundtrip_prefix_parse(self) -> None:
        """Prefixed name can be parsed back to (server, tool)."""
        from myrm_agent_harness.toolkits.mcp.config import parse_mcp_tool_name

        tools = [_make_tool(name="search_repos")]
        prefix_tool_names(tools, "github")
        result = parse_mcp_tool_name(tools[0].name)
        assert result == ("github", "search_repos")


class TestParseMcpToolName:
    def test_valid_name(self) -> None:
        from myrm_agent_harness.toolkits.mcp.config import parse_mcp_tool_name

        result = parse_mcp_tool_name("mcp__github__search_repos")
        assert result == ("github", "search_repos")

    def test_server_with_underscore(self) -> None:
        from myrm_agent_harness.toolkits.mcp.config import parse_mcp_tool_name

        result = parse_mcp_tool_name("mcp__github_actions__run")
        assert result == ("github_actions", "run")

    def test_non_mcp_name(self) -> None:
        from myrm_agent_harness.toolkits.mcp.config import parse_mcp_tool_name

        assert parse_mcp_tool_name("file_read_tool") is None

    def test_is_mcp_tool_name(self) -> None:
        from myrm_agent_harness.toolkits.mcp.config import is_mcp_tool_name

        assert is_mcp_tool_name("mcp__github__search") is True
        assert is_mcp_tool_name("file_read_tool") is False
        assert is_mcp_tool_name("mcp__") is False

    def test_no_tool_delimiter(self) -> None:
        from myrm_agent_harness.toolkits.mcp.config import parse_mcp_tool_name

        assert parse_mcp_tool_name("mcp__serveronly") is None

    def test_empty_server(self) -> None:
        from myrm_agent_harness.toolkits.mcp.config import parse_mcp_tool_name

        assert parse_mcp_tool_name("mcp____tool") is None

    def test_empty_tool_part(self) -> None:
        from myrm_agent_harness.toolkits.mcp.config import parse_mcp_tool_name

        result = parse_mcp_tool_name("mcp__server__")
        assert result == ("server", "")

    def test_tool_with_nested_double_underscore(self) -> None:
        from myrm_agent_harness.toolkits.mcp.config import parse_mcp_tool_name

        result = parse_mcp_tool_name("mcp__server__tool__extra")
        assert result == ("server", "tool__extra")

    def test_is_mcp_tool_name_edge_cases(self) -> None:
        from myrm_agent_harness.toolkits.mcp.config import is_mcp_tool_name

        assert is_mcp_tool_name("mcp__s__t") is True
        assert is_mcp_tool_name("mcp__a__") is True
        assert is_mcp_tool_name("MCP__server__tool") is False
        assert is_mcp_tool_name("") is False

    def test_parse_empty_string(self) -> None:
        from myrm_agent_harness.toolkits.mcp.config import parse_mcp_tool_name

        assert parse_mcp_tool_name("") is None


class TestPrefixEdgeCases:
    def test_empty_tool_list(self) -> None:
        tools: list[StructuredTool] = []
        prefix_tool_names(tools, "srv")
        assert tools == []

    def test_annotations_use_prefixed_names(self) -> None:
        """_register_tool_annotations runs after prefix — tool.name is prefixed."""
        tools = [_make_tool(name="search", metadata={"readOnlyHint": True})]
        result = MCPAgent.process_session_tools(tools, "gh", None, None, 10.0)
        assert result[0].name == "mcp__gh__search"

    def test_sanitize_none_input(self) -> None:
        from myrm_agent_harness.toolkits.mcp.config import sanitize_mcp_name_component

        assert sanitize_mcp_name_component(None) == "unnamed"  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# _coerce_content_block: LLM-safe content block coercion
# ---------------------------------------------------------------------------
class TestCoerceContentBlock:
    """Tests for coerce_content_block — ensures only LLM-safe block types."""

    def test_text_passthrough(self) -> None:
        block = {"type": "text", "text": "hello world"}
        assert coerce_content_block(block) is block

    def test_image_with_base64_passthrough(self) -> None:
        block = {"type": "image", "base64": "abc123", "mime_type": "image/png"}
        assert coerce_content_block(block) is block

    def test_image_with_data_passthrough(self) -> None:
        block = {"type": "image", "data": "abc123", "mime_type": "image/png"}
        assert coerce_content_block(block) is block

    def test_image_with_url_passthrough(self) -> None:
        block = {
            "type": "image",
            "url": "https://example.com/img.png",
            "mime_type": "image/png",
        }
        assert coerce_content_block(block) is block

    def test_malformed_image_degraded(self) -> None:
        block = {"type": "image", "mime_type": "image/png"}
        result = coerce_content_block(block)
        assert result["type"] == "text"
        assert "image" in str(result["text"])

    def test_file_block_degraded_with_url(self) -> None:
        block = {
            "type": "file",
            "url": "https://notion.so/page/xxx",
            "mime_type": "application/pdf",
        }
        result = coerce_content_block(block)
        assert result["type"] == "text"
        assert "https://notion.so/page/xxx" in str(result["text"])

    def test_file_block_degraded_without_url(self) -> None:
        block = {"type": "file", "mime_type": "audio/wav"}
        result = coerce_content_block(block)
        assert result["type"] == "text"
        assert "audio/wav" in str(result["text"])

    def test_unknown_type_degraded(self) -> None:
        block = {"type": "video", "data": "binary_data"}
        result = coerce_content_block(block)
        assert result["type"] == "text"
        assert "video" in str(result["text"])

    def test_none_type_degraded(self) -> None:
        block = {"text": "no type field"}
        result = coerce_content_block(block)
        assert result["type"] == "text"


# ---------------------------------------------------------------------------
# _normalize_mcp_result with coercion: session poison prevention
# ---------------------------------------------------------------------------
class TestNormalizeMcpResultCoercion:
    """Tests for _normalize_mcp_result with _coerce_content_block integration."""

    def test_text_only_returns_string(self) -> None:
        result = CallToolResult(content=[TextContent(type="text", text="hello")])
        assert normalize_mcp_result(result) == "hello"

    def test_image_returns_list(self) -> None:
        result = CallToolResult(
            content=[
                TextContent(type="text", text="caption"),
                ImageContent(type="image", data="abc", mime_type="image/png"),
            ]
        )
        normalized = normalize_mcp_result(result)
        assert isinstance(normalized, list)
        assert len(normalized) == 2

    def test_file_block_degraded_to_text(self) -> None:
        """file blocks (from ResourceLink) must be degraded — prevents Anthropic 400."""
        result = CallToolResult(
            content=[
                TextContent(type="text", text="Sprint Board"),
                ResourceLink(
                    type="resource_link",
                    uri="https://notion.so/page/xxx",
                    name="page",
                    mime_type="application/pdf",
                ),
            ]
        )
        normalized = normalize_mcp_result(result)
        assert isinstance(normalized, str)
        assert "Sprint Board" in normalized
        assert "https://notion.so/page/xxx" in normalized

    def test_mixed_file_and_image_preserves_image(self) -> None:
        """When both file and image are present, image passes through, file degrades."""
        result = CallToolResult(
            content=[
                ImageContent(type="image", data="abc", mime_type="image/png"),
                ResourceLink(
                    type="resource_link",
                    uri="https://example.com/doc.pdf",
                    name="doc",
                    mime_type="application/pdf",
                ),
            ]
        )
        normalized = normalize_mcp_result(result)
        assert isinstance(normalized, list)
        assert normalized[0]["type"] == "image"
        assert normalized[1]["type"] == "text"
        assert "https://example.com/doc.pdf" in str(normalized[1]["text"])

    def test_structured_content_appended(self) -> None:
        result = CallToolResult(
            content=[TextContent(type="text", text="data")],
            structured_content={"key": "val"},
        )
        normalized = normalize_mcp_result(result)
        assert isinstance(normalized, str)
        assert "key" in normalized
        assert "val" in normalized

    def test_is_error_collapses_to_error_string(self) -> None:
        result = CallToolResult(
            content=[TextContent(type="text", text="invalid args")],
            is_error=True,
        )
        normalized = normalize_mcp_result(result)
        assert isinstance(normalized, str)
        assert "[MCP tool error]" in normalized
        assert "invalid args" in normalized

    def test_is_error_with_structured_details(self) -> None:
        """Error details in structured_content surface even when text is empty."""
        result = CallToolResult(
            content=[TextContent(type="text", text="")],
            structured_content={
                "error": "permission denied",
                "code": 403,
            },
            is_error=True,
        )
        normalized = normalize_mcp_result(result)
        assert isinstance(normalized, str)
        assert "permission denied" in normalized
        assert "403" in normalized

    def test_is_error_structured_appended_without_duplication(self) -> None:
        """structured details append to a short text message, not duplicated."""
        result = CallToolResult(
            content=[TextContent(type="text", text="invalid args")],
            structured_content={"details": "field qty must be > 0, got -5"},
            is_error=True,
        )
        normalized = normalize_mcp_result(result)
        assert isinstance(normalized, str)
        assert "invalid args" in normalized
        assert "field qty must be > 0" in normalized

    def test_is_error_structured_mirrored_in_text_not_duplicated(self) -> None:
        """When text already mirrors the serialized JSON, no duplication occurs."""
        result = CallToolResult(
            content=[
                TextContent(
                    type="text",
                    text='{"error": "oops"}',
                )
            ],
            structured_content={"error": "oops"},
            is_error=True,
        )
        normalized = normalize_mcp_result(result)
        assert isinstance(normalized, str)
        assert normalized.count('"error"') == 1

    def test_plain_string_result(self) -> None:
        assert normalize_mcp_result("just text") == "just text"

    def test_non_standard_block_coerced_to_text(self) -> None:
        """Non-ContentBlock entries in content degrade to text instead of crashing."""
        from types import SimpleNamespace

        raw = SimpleNamespace(
            content=[42, "raw_str"],
        )
        normalized = normalize_mcp_result(raw)
        assert isinstance(normalized, str)
        assert "42" in normalized
        assert "raw_str" in normalized

    def test_non_tuple_non_string_stringified(self) -> None:
        result = normalize_mcp_result(12345)
        assert result == "12345"


# ---------------------------------------------------------------------------
# _timeout_wrapper: upstream fault tolerance
# ---------------------------------------------------------------------------
class TestTimeoutWrapperFaultTolerance:
    """Tests for _timeout_wrapper catching adapter-layer exceptions."""

    @pytest.mark.asyncio
    async def test_not_implemented_error_caught(self) -> None:
        """AudioContent raising NotImplementedError must not crash the timeout wrapper."""

        async def raise_not_impl(*_a, **_kw):
            raise NotImplementedError("AudioContent not supported")

        tool = _make_tool(coroutine=raise_not_impl)
        wrap_tools_with_timeout([tool], timeout=5.0)

        result = await tool.coroutine()
        assert isinstance(result, str)
        assert "unsupported content" in result
        assert "AudioContent" in result
        assert "UNTRUSTED_DATA" not in result

    @pytest.mark.asyncio
    async def test_value_error_caught(self) -> None:
        """Unknown MCP content type raises ValueError — must not crash."""

        async def raise_value_err(*_a, **_kw):
            raise ValueError("Unknown MCP content type: FutureContent")

        tool = _make_tool(coroutine=raise_value_err)
        wrap_tools_with_timeout([tool], timeout=5.0)

        result = await tool.coroutine()
        assert isinstance(result, str)
        assert "unsupported content" in result
        assert "UNTRUSTED_DATA" not in result

    @pytest.mark.asyncio
    async def test_type_error_caught(self) -> None:
        """Type mismatch in adapter layer — must not crash."""

        async def raise_type_err(*_a, **_kw):
            raise TypeError("expected str, got NoneType")

        tool = _make_tool(coroutine=raise_type_err)
        wrap_tools_with_timeout([tool], timeout=5.0)

        result = await tool.coroutine()
        assert isinstance(result, str)
        assert "unsupported content" in result
        assert "UNTRUSTED_DATA" not in result

    @pytest.mark.asyncio
    async def test_other_exceptions_still_propagate(self) -> None:
        """Exceptions not in the catch list must still propagate."""

        async def raise_runtime(*_a, **_kw):
            raise RuntimeError("unexpected crash")

        tool = _make_tool(coroutine=raise_runtime)
        wrap_tools_with_timeout([tool], timeout=5.0)

        with pytest.raises(RuntimeError, match="unexpected crash"):
            await tool.coroutine()


class TestExtractMcpAppMetadata:
    """Tests for extract_mcp_app_metadata — ext-apps UI detection."""

    def test_valid_artifact_with_resource_uri(self) -> None:
        artifact = {
            "_meta": {"ui": {"resourceUri": "ui://weather/dashboard"}},
            "structured_content": {"temp": 22},
        }
        result = extract_mcp_app_metadata(artifact)
        assert result == {
            "resource_uri": "ui://weather/dashboard",
            "structured_content": {"temp": 22},
        }

    def test_valid_artifact_without_structured_content(self) -> None:
        artifact = {"_meta": {"ui": {"resourceUri": "ui://charts/pie"}}}
        result = extract_mcp_app_metadata(artifact)
        assert result == {"resource_uri": "ui://charts/pie"}

    def test_none_artifact(self) -> None:
        assert extract_mcp_app_metadata(None) is None

    def test_no_meta_key(self) -> None:
        assert extract_mcp_app_metadata({"data": "hello"}) is None

    def test_meta_without_ui(self) -> None:
        assert extract_mcp_app_metadata({"_meta": {"version": 1}}) is None

    def test_ui_without_resource_uri(self) -> None:
        assert (
            extract_mcp_app_metadata({"_meta": {"ui": {"height": 300}}})
            is None
        )

    def test_empty_resource_uri(self) -> None:
        assert (
            extract_mcp_app_metadata({"_meta": {"ui": {"resourceUri": ""}}})
            is None
        )

    def test_non_string_resource_uri(self) -> None:
        assert (
            extract_mcp_app_metadata({"_meta": {"ui": {"resourceUri": 123}}})
            is None
        )

    def test_non_dict_meta(self) -> None:
        assert extract_mcp_app_metadata({"_meta": "not a dict"}) is None

    def test_non_dict_ui(self) -> None:
        assert extract_mcp_app_metadata({"_meta": {"ui": "string"}}) is None


class TestEmitMcpAppEvent:
    """Tests for emit_mcp_app_event — SSE event emission via progress_sink."""

    @pytest.mark.asyncio
    async def test_emits_event_for_valid_artifact(self) -> None:
        mock_sink = AsyncMock()
        raw_result = CallToolResult(
            content=[TextContent(type="text", text="text content")],
            _meta={"ui": {"resourceUri": "ui://srv/view"}},
        )

        with patch(
            "myrm_agent_harness.utils.runtime.progress_sink.get_tool_progress_sink",
            return_value=mock_sink,
        ):
            await emit_mcp_app_event(raw_result, "mcp__weather__forecast")

        mock_sink.emit.assert_called_once()
        event = mock_sink.emit.call_args[0][0]
        assert event["mcp_app"]["resource_uri"] == "ui://srv/view"
        assert event["mcp_app"]["server_name"] == "weather"

    @pytest.mark.asyncio
    async def test_includes_structured_content(self) -> None:
        mock_sink = AsyncMock()
        raw_result = CallToolResult(
            content=[TextContent(type="text", text="txt")],
            structured_content={"key": "val"},
            _meta={"ui": {"resourceUri": "ui://a/b"}},
        )

        with patch(
            "myrm_agent_harness.utils.runtime.progress_sink.get_tool_progress_sink",
            return_value=mock_sink,
        ):
            await emit_mcp_app_event(raw_result, "mcp__srv__tool")

        event = mock_sink.emit.call_args[0][0]
        assert event["mcp_app"]["structured_content"] == {"key": "val"}

    @pytest.mark.asyncio
    async def test_skips_non_tuple_result(self) -> None:
        mock_sink = AsyncMock()
        with patch(
            "myrm_agent_harness.utils.runtime.progress_sink.get_tool_progress_sink",
            return_value=mock_sink,
        ):
            await emit_mcp_app_event("plain string", "mcp__s__t")
        mock_sink.emit.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_tuple_without_ext_apps_meta(self) -> None:
        mock_sink = AsyncMock()
        raw_result = CallToolResult(content=[TextContent(type="text", text="text")])
        with patch(
            "myrm_agent_harness.utils.runtime.progress_sink.get_tool_progress_sink",
            return_value=mock_sink,
        ):
            await emit_mcp_app_event(raw_result, "mcp__s__t")
        mock_sink.emit.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_no_progress_sink(self) -> None:
        raw_result = CallToolResult(
            content=[TextContent(type="text", text="txt")],
            _meta={"ui": {"resourceUri": "ui://x/y"}},
        )
        with patch(
            "myrm_agent_harness.utils.runtime.progress_sink.get_tool_progress_sink",
            return_value=None,
        ):
            # Should not raise
            await emit_mcp_app_event(raw_result, "mcp__s__t")

    @pytest.mark.asyncio
    async def test_handles_emit_exception_gracefully(self) -> None:
        mock_sink = AsyncMock()
        mock_sink.emit.side_effect = RuntimeError("sink broken")
        raw_result = CallToolResult(
            content=[TextContent(type="text", text="txt")],
            _meta={"ui": {"resourceUri": "ui://x/y"}},
        )
        with patch(
            "myrm_agent_harness.utils.runtime.progress_sink.get_tool_progress_sink",
            return_value=mock_sink,
        ):
            # Should not raise, just log
            await emit_mcp_app_event(raw_result, "mcp__s__t")

    @pytest.mark.asyncio
    async def test_non_mcp_tool_name_yields_empty_server(self) -> None:
        mock_sink = AsyncMock()
        raw_result = CallToolResult(
            content=[TextContent(type="text", text="txt")],
            _meta={"ui": {"resourceUri": "ui://x/y"}},
        )
        with patch(
            "myrm_agent_harness.utils.runtime.progress_sink.get_tool_progress_sink",
            return_value=mock_sink,
        ):
            await emit_mcp_app_event(raw_result, "regular_tool")
        event = mock_sink.emit.call_args[0][0]
        assert event["mcp_app"]["server_name"] == ""


# ---------------------------------------------------------------------------
# _wrap_tools_with_timeout: MCP transport 401 -> re-authorization message.
# ---------------------------------------------------------------------------


class TestWrapToolsAuthError:
    """The 401 path surfaces a re-authorization message instead of a raise."""

    @pytest.mark.asyncio
    async def test_http_401_returns_reauthorization_message(self) -> None:
        import httpx2

        request = MagicMock()
        response = MagicMock()
        response.status_code = 401
        err = httpx2.HTTPStatusError(
            "401 Unauthorized", request=request, response=response
        )

        tool = _make_tool(
            name="mcp__auth_server__read",
            coroutine=AsyncMock(side_effect=err),
        )
        with patch(
            "myrm_agent_harness.toolkits.mcp.tool_processing._emit_auth_expired_for_tool"
        ) as mock_emit:
            wrap_tools_with_timeout([tool], timeout=5.0)
            result = await tool.ainvoke({"a": "1"})

        assert "auth_server" in result
        assert "requires re-authorization" in result
        mock_emit.assert_called_once()

    @pytest.mark.asyncio
    async def test_non_401_status_error_still_raises(self) -> None:
        import httpx2

        request = MagicMock()
        response = MagicMock()
        response.status_code = 500
        err = httpx2.HTTPStatusError(
            "500 Internal Server Error", request=request, response=response
        )

        tool = _make_tool(name="mcp__srv__boom", coroutine=AsyncMock(side_effect=err))
        wrap_tools_with_timeout([tool], timeout=5.0)
        with pytest.raises(httpx2.HTTPStatusError):
            await tool.ainvoke({"a": "1"})

    @pytest.mark.asyncio
    async def test_unauth_tool_name_yields_full_name_fallback(self) -> None:
        import httpx2

        request = MagicMock()
        response = MagicMock()
        response.status_code = 401
        err = httpx2.HTTPStatusError(
            "401 Unauthorized", request=request, response=response
        )

        tool = _make_tool(name="plain_tool", coroutine=AsyncMock(side_effect=err))
        with patch(
            "myrm_agent_harness.toolkits.mcp.tool_processing._emit_auth_expired_for_tool"
        ):
            wrap_tools_with_timeout([tool], timeout=5.0)
            result = await tool.ainvoke({"a": "1"})

        # No mcp__server__tool prefix -> falls back to the raw tool name.
        assert "plain_tool" in result
        assert "requires re-authorization" in result
