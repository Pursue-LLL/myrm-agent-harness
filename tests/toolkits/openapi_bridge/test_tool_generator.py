"""Tests for openapi_bridge.tool_generator module.

Validates tool generation, namespace isolation, endpoint filtering,
caching behavior, and the OpenAPIBridge facade.
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.toolkits.openapi_bridge.config import (
    OpenAPIServiceConfig,
    ParsedEndpoint,
)
from myrm_agent_harness.toolkits.openapi_bridge.spec_parser import ParsedSpec
from myrm_agent_harness.toolkits.openapi_bridge.tool_generator import (
    OpenAPIBridge,
    generate_tools,
)


def _make_spec(endpoints: list[ParsedEndpoint] | None = None) -> ParsedSpec:
    """Create a minimal ParsedSpec for testing."""
    if endpoints is None:
        endpoints = [
            ParsedEndpoint(operation_id="listPets", method="GET", path="/pets", summary="List pets"),
            ParsedEndpoint(operation_id="getPet", method="GET", path="/pets/{petId}", summary="Get pet by ID"),
            ParsedEndpoint(operation_id="createPet", method="POST", path="/pets", summary="Create pet"),
            ParsedEndpoint(
                operation_id="oldEndpoint", method="GET", path="/old", summary="Deprecated", deprecated=True
            ),
        ]
    return ParsedSpec(
        title="Test API",
        version="1.0",
        base_url="https://api.test.io",
        spec_version="openapi_3x",
        endpoints=endpoints,
    )


def _make_config(
    name: str = "test_api",
    selected_endpoints: list[str] | None = None,
    base_url: str | None = None,
) -> OpenAPIServiceConfig:
    """Create a minimal OpenAPIServiceConfig for testing."""
    return OpenAPIServiceConfig(
        name=name,
        spec_url="https://example.com/spec.json",
        selected_endpoints=selected_endpoints or [],
        base_url=base_url,
    )


class TestGenerateTools:
    """Test the generate_tools function."""

    @pytest.mark.asyncio
    async def test_generates_tools_for_all_non_deprecated(self):
        spec = _make_spec()
        config = _make_config()
        tools = await generate_tools(config, spec)
        # 4 endpoints, 1 deprecated → 3 tools
        assert len(tools) == 3

    @pytest.mark.asyncio
    async def test_namespace_isolation(self):
        spec = _make_spec()
        config = _make_config(name="petstore")
        tools = await generate_tools(config, spec)
        for tool in tools:
            assert tool.name.startswith("petstore_")

    @pytest.mark.asyncio
    async def test_tool_names(self):
        spec = _make_spec()
        config = _make_config(name="api")
        tools = await generate_tools(config, spec)
        tool_names = [t.name for t in tools]
        assert "api_listPets" in tool_names
        assert "api_getPet" in tool_names
        assert "api_createPet" in tool_names
        assert "api_oldEndpoint" not in tool_names

    @pytest.mark.asyncio
    async def test_endpoint_selection_filter(self):
        spec = _make_spec()
        config = _make_config(selected_endpoints=["listPets", "createPet"])
        tools = await generate_tools(config, spec)
        assert len(tools) == 2
        tool_names = [t.name for t in tools]
        assert "test_api_listPets" in tool_names
        assert "test_api_createPet" in tool_names
        assert "test_api_getPet" not in tool_names

    @pytest.mark.asyncio
    async def test_tool_descriptions(self):
        spec = _make_spec()
        config = _make_config()
        tools = await generate_tools(config, spec)
        tool_map = {t.name: t for t in tools}
        assert "List pets" in tool_map["test_api_listPets"].description
        assert "[GET /pets]" in tool_map["test_api_listPets"].description

    @pytest.mark.asyncio
    async def test_raises_without_base_url(self):
        spec = ParsedSpec(
            title="T",
            version="1",
            base_url="",
            endpoints=[
                ParsedEndpoint(operation_id="op", method="GET", path="/x", summary="X"),
            ],
        )
        config = OpenAPIServiceConfig(name="no_url", spec_url="https://x.com/s.json")
        with pytest.raises(ValueError, match="No base URL"):
            await generate_tools(config, spec)

    @pytest.mark.asyncio
    async def test_config_base_url_overrides_spec(self):
        spec = _make_spec()
        config = _make_config(base_url="https://custom.api.io")
        tools = await generate_tools(config, spec)
        # Tools should exist (base_url from config is used)
        assert len(tools) == 3


class TestToolExecution:
    """Test that generated tools correctly route parameters."""

    @pytest.mark.asyncio
    async def test_path_params_passed_correctly(self):
        """Verify path parameters are correctly extracted and passed."""
        endpoints = [
            ParsedEndpoint(operation_id="getPet", method="GET", path="/pets/{petId}", summary="Get pet"),
        ]
        spec = _make_spec(endpoints=endpoints)
        config = _make_config()

        with patch(
            "myrm_agent_harness.toolkits.openapi_bridge.tool_generator.OpenAPIExecutor",
        ) as MockExecutorCls:  # noqa: N806 mock 类名别名
            mock_executor = AsyncMock()
            mock_executor.execute.return_value = '{"id": "123", "name": "Rex"}'
            MockExecutorCls.return_value = mock_executor

            tools = await generate_tools(config, spec)
            get_pet_tool = tools[0]
            # Agent runtime calls coroutine directly with kwargs
            await get_pet_tool.coroutine(petId="123")

        mock_executor.execute.assert_called_once()
        call_kwargs = mock_executor.execute.call_args[1]
        assert call_kwargs["path_params"] == {"petId": "123"}

    @pytest.mark.asyncio
    async def test_post_body_handling(self):
        """Verify POST params (non-path) are routed to request body."""
        endpoints = [
            ParsedEndpoint(operation_id="createPet", method="POST", path="/pets", summary="Create pet"),
        ]
        spec = _make_spec(endpoints=endpoints)
        config = _make_config()

        with patch(
            "myrm_agent_harness.toolkits.openapi_bridge.tool_generator.OpenAPIExecutor",
        ) as MockExecutorCls:  # noqa: N806 mock 类名别名
            mock_executor = AsyncMock()
            mock_executor.execute.return_value = '{"id": "new"}'
            MockExecutorCls.return_value = mock_executor

            tools = await generate_tools(config, spec)
            create_tool = tools[0]
            # Agent runtime calls coroutine directly with kwargs
            await create_tool.coroutine(name="Rex", type="dog")

        mock_executor.execute.assert_called_once()
        call_kwargs = mock_executor.execute.call_args[1]
        assert call_kwargs["body"] == {"name": "Rex", "type": "dog"}

    @pytest.mark.asyncio
    async def test_args_schema_exposes_query_and_body_fields(self):
        """Tool args_schema carries schema-declared query/body parameters."""
        endpoints = [
            ParsedEndpoint(
                operation_id="createOrder",
                method="POST",
                path="/orders",
                summary="Create order",
                param_schema={
                    "type": "object",
                    "properties": {
                        "source": {"type": "string"},
                        "product_id": {"type": "integer"},
                    },
                    "required": ["product_id"],
                },
                query_param_keys={"source"},
            ),
        ]
        spec = _make_spec(endpoints=endpoints)
        config = _make_config()
        tools = await generate_tools(config, spec)
        args_schema = tools[0].args_schema
        props = args_schema["properties"]
        assert props["source"] == {"type": "string"}
        assert props["product_id"] == {"type": "integer"}
        assert args_schema["required"] == ["product_id"]

    @pytest.mark.asyncio
    async def test_post_body_string_number_coerced_to_int(self):
        """LLM-emitted string numbers are coerced against the body schema."""
        endpoints = [
            ParsedEndpoint(
                operation_id="createOrder",
                method="POST",
                path="/orders",
                summary="Create order",
                param_schema={
                    "type": "object",
                    "properties": {
                        "product_id": {"type": "integer"},
                        "amount": {"type": "number"},
                    },
                },
            ),
        ]
        spec = _make_spec(endpoints=endpoints)
        config = _make_config()

        with patch(
            "myrm_agent_harness.toolkits.openapi_bridge.tool_generator.OpenAPIExecutor",
        ) as MockExecutorCls:  # noqa: N806 mock 类名别名
            mock_executor = AsyncMock()
            mock_executor.execute.return_value = '{"id": "new"}'
            MockExecutorCls.return_value = mock_executor

            tools = await generate_tools(config, spec)
            await tools[0].coroutine(product_id="99021", amount="2500")

        call_kwargs = mock_executor.execute.call_args[1]
        assert call_kwargs["body"] == {"product_id": 99021, "amount": 2500}
        assert isinstance(call_kwargs["body"]["product_id"], int)
        assert isinstance(call_kwargs["body"]["amount"], int)

    @pytest.mark.asyncio
    async def test_post_body_big_integer_preserves_precision(self):
        """2**53+1-style big integer IDs survive coercion without float rounding."""
        endpoints = [
            ParsedEndpoint(
                operation_id="lookup",
                method="POST",
                path="/lookup",
                summary="Lookup",
                param_schema={
                    "type": "object",
                    "properties": {"snowflake_id": {"type": "number"}},
                },
            ),
        ]
        spec = _make_spec(endpoints=endpoints)
        config = _make_config()

        with patch(
            "myrm_agent_harness.toolkits.openapi_bridge.tool_generator.OpenAPIExecutor",
        ) as MockExecutorCls:  # noqa: N806 mock 类名别名
            mock_executor = AsyncMock()
            mock_executor.execute.return_value = '{"ok": true}'
            MockExecutorCls.return_value = mock_executor

            tools = await generate_tools(config, spec)
            await tools[0].coroutine(snowflake_id="9007199254740993")

        call_kwargs = mock_executor.execute.call_args[1]
        assert call_kwargs["body"] == {"snowflake_id": 9007199254740993}
        assert isinstance(call_kwargs["body"]["snowflake_id"], int)

    @pytest.mark.asyncio
    async def test_query_number_coerced_and_serialized_as_string(self):
        """Schema-declared query params route to the query string after coercion."""
        endpoints = [
            ParsedEndpoint(
                operation_id="listOrders",
                method="GET",
                path="/orders",
                summary="List orders",
                param_schema={
                    "type": "object",
                    "properties": {"limit": {"type": "integer"}},
                },
                query_param_keys={"limit"},
            ),
        ]
        spec = _make_spec(endpoints=endpoints)
        config = _make_config()

        with patch(
            "myrm_agent_harness.toolkits.openapi_bridge.tool_generator.OpenAPIExecutor",
        ) as MockExecutorCls:  # noqa: N806 mock 类名别名
            mock_executor = AsyncMock()
            mock_executor.execute.return_value = "[]"
            MockExecutorCls.return_value = mock_executor

            tools = await generate_tools(config, spec)
            await tools[0].coroutine(limit="10")

        call_kwargs = mock_executor.execute.call_args[1]
        assert call_kwargs["query_params"] == {"limit": "10"}
        assert call_kwargs["body"] is None

    @pytest.mark.asyncio
    async def test_post_body_array_sent_as_request_body(self):
        """Spec-declared array request bodies are sent directly, not nested."""
        endpoints = [
            ParsedEndpoint(
                operation_id="bulkCreate",
                method="POST",
                path="/items/bulk",
                summary="Bulk create",
                param_schema={
                    "type": "object",
                    "properties": {"body": {"type": "array", "items": {"type": "object"}}},
                },
            ),
        ]
        spec = _make_spec(endpoints=endpoints)
        config = _make_config()

        with patch(
            "myrm_agent_harness.toolkits.openapi_bridge.tool_generator.OpenAPIExecutor",
        ) as MockExecutorCls:  # noqa: N806 mock 类名别名
            mock_executor = AsyncMock()
            mock_executor.execute.return_value = "[]"
            MockExecutorCls.return_value = mock_executor

            tools = await generate_tools(config, spec)
            await tools[0].coroutine(body=[{"id": 1}, {"id": 2}])

        call_kwargs = mock_executor.execute.call_args[1]
        assert call_kwargs["body"] == [{"id": 1}, {"id": 2}]

    @pytest.mark.asyncio
    async def test_post_body_object_sent_as_request_body(self):
        """Schema-declared object request bodies are sent directly."""
        endpoints = [
            ParsedEndpoint(
                operation_id="createUser",
                method="POST",
                path="/users",
                summary="Create user",
                param_schema={
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                },
            ),
        ]
        spec = _make_spec(endpoints=endpoints)
        config = _make_config()

        with patch(
            "myrm_agent_harness.toolkits.openapi_bridge.tool_generator.OpenAPIExecutor",
        ) as MockExecutorCls:  # noqa: N806 mock 类名别名
            mock_executor = AsyncMock()
            mock_executor.execute.return_value = "{}"
            MockExecutorCls.return_value = mock_executor

            tools = await generate_tools(config, spec)
            await tools[0].coroutine(name="Alice")

        call_kwargs = mock_executor.execute.call_args[1]
        assert call_kwargs["body"] == {"name": "Alice"}

    @pytest.mark.asyncio
    async def test_post_body_string_kept_verbatim(self):
        """Spec-declared string bodies are sent verbatim, never wrapped."""
        endpoints = [
            ParsedEndpoint(
                operation_id="echo",
                method="POST",
                path="/echo",
                summary="Echo body",
                param_schema={
                    "type": "object",
                    "properties": {"body": {"type": "string"}},
                },
            ),
        ]
        spec = _make_spec(endpoints=endpoints)
        config = _make_config()

        with patch(
            "myrm_agent_harness.toolkits.openapi_bridge.tool_generator.OpenAPIExecutor",
        ) as MockExecutorCls:  # noqa: N806 mock 类名别名
            mock_executor = AsyncMock()
            mock_executor.execute.return_value = "ok"
            MockExecutorCls.return_value = mock_executor

            tools = await generate_tools(config, spec)
            await tools[0].coroutine(body="hello")
            assert mock_executor.execute.call_args[1]["body"] == "hello"
            # A numeric-looking string body is also kept verbatim, not int-cast.
            await tools[0].coroutine(body="123")
            assert mock_executor.execute.call_args[1]["body"] == "123"

    @pytest.mark.asyncio
    async def test_post_body_json_string_parsed_to_object(self):
        """Weak models emitting stringified JSON bodies still route correctly."""
        endpoints = [
            ParsedEndpoint(
                operation_id="createOrder",
                method="POST",
                path="/orders",
                summary="Create order",
                param_schema={
                    "type": "object",
                    "properties": {"body": {"type": "object"}},
                },
            ),
        ]
        spec = _make_spec(endpoints=endpoints)
        config = _make_config()

        with patch(
            "myrm_agent_harness.toolkits.openapi_bridge.tool_generator.OpenAPIExecutor",
        ) as MockExecutorCls:  # noqa: N806 mock 类名别名
            mock_executor = AsyncMock()
            mock_executor.execute.return_value = "{}"
            MockExecutorCls.return_value = mock_executor

            tools = await generate_tools(config, spec)
            await tools[0].coroutine(body='{"id": 42}')

        call_kwargs = mock_executor.execute.call_args[1]
        assert call_kwargs["body"] == {"id": 42}

    @pytest.mark.asyncio
    async def test_query_object_serialized_as_compact_json(self):
        """Object query params serialize to compact JSON, not Python repr."""
        endpoints = [
            ParsedEndpoint(
                operation_id="listItems",
                method="GET",
                path="/items",
                summary="List items",
                param_schema={
                    "type": "object",
                    "properties": {"filter": {"type": "object"}},
                },
                query_param_keys={"filter"},
            ),
        ]
        spec = _make_spec(endpoints=endpoints)
        config = _make_config()

        with patch(
            "myrm_agent_harness.toolkits.openapi_bridge.tool_generator.OpenAPIExecutor",
        ) as MockExecutorCls:  # noqa: N806 mock 类名别名
            mock_executor = AsyncMock()
            mock_executor.execute.return_value = "[]"
            MockExecutorCls.return_value = mock_executor

            tools = await generate_tools(config, spec)
            await tools[0].coroutine(filter={"status": "shipped"})

        call_kwargs = mock_executor.execute.call_args[1]
        assert call_kwargs["query_params"] == {"filter": '{"status":"shipped"}'}

    @pytest.mark.asyncio
    async def test_query_bool_serialized_lowercase(self):
        """Boolean query params serialize lowercase (true/false), not Python True."""
        endpoints = [
            ParsedEndpoint(
                operation_id="listItems2",
                method="GET",
                path="/items",
                summary="List items",
                param_schema={
                    "type": "object",
                    "properties": {"paginated": {"type": "boolean"}},
                },
                query_param_keys={"paginated"},
            ),
        ]
        spec = _make_spec(endpoints=endpoints)
        config = _make_config()

        with patch(
            "myrm_agent_harness.toolkits.openapi_bridge.tool_generator.OpenAPIExecutor",
        ) as MockExecutorCls:  # noqa: N806 mock 类名别名
            mock_executor = AsyncMock()
            mock_executor.execute.return_value = "[]"
            MockExecutorCls.return_value = mock_executor

            tools = await generate_tools(config, spec)
            await tools[0].coroutine(paginated=True)

        call_kwargs = mock_executor.execute.call_args[1]
        assert call_kwargs["query_params"] == {"paginated": "true"}

    @pytest.mark.asyncio
    async def test_query_none_parameter_omitted(self):
        """Null query params are omitted from the query string, not sent as 'None'."""
        endpoints = [
            ParsedEndpoint(
                operation_id="listItems3",
                method="GET",
                path="/items",
                summary="List items",
                param_schema={
                    "type": "object",
                    "properties": {"status": {"type": ["string", "null"]}},
                },
                query_param_keys={"status"},
            ),
        ]
        spec = _make_spec(endpoints=endpoints)
        config = _make_config()

        with patch(
            "myrm_agent_harness.toolkits.openapi_bridge.tool_generator.OpenAPIExecutor",
        ) as MockExecutorCls:  # noqa: N806 mock 类名别名
            mock_executor = AsyncMock()
            mock_executor.execute.return_value = "[]"
            MockExecutorCls.return_value = mock_executor

            tools = await generate_tools(config, spec)
            await tools[0].coroutine(status=None)

        call_kwargs = mock_executor.execute.call_args[1]
        assert call_kwargs["query_params"] is None or "status" not in (call_kwargs["query_params"] or {})


class TestOpenAPIBridge:
    """Test the OpenAPIBridge facade class."""

    @pytest.mark.asyncio
    async def test_get_tools_from_url(self):
        spec = _make_spec()
        config = _make_config()

        with patch.object(OpenAPIBridge, "_parse_spec", new_callable=AsyncMock) as mock_parse:
            mock_parse.return_value = spec
            bridge = OpenAPIBridge()
            tools = await bridge.get_tools(config)

        assert len(tools) == 3
        mock_parse.assert_called_once_with(config)

    @pytest.mark.asyncio
    async def test_get_tools_batch(self):
        spec = _make_spec()
        config1 = _make_config(name="svc1")
        config2 = _make_config(name="svc2")
        config_disabled = OpenAPIServiceConfig(name="disabled", spec_url="https://x.com/s.json", enabled=False)

        with patch.object(OpenAPIBridge, "_parse_spec", new_callable=AsyncMock) as mock_parse:
            mock_parse.return_value = spec
            bridge = OpenAPIBridge()
            tools = await bridge.get_tools_batch([config1, config2, config_disabled])

        # 3 tools per enabled service × 2 services = 6
        assert len(tools) == 6
        # Disabled service should not be called
        assert mock_parse.call_count == 2

    @pytest.mark.asyncio
    async def test_preview_spec(self):
        spec = _make_spec()
        config = _make_config()

        with patch.object(OpenAPIBridge, "_parse_spec", new_callable=AsyncMock) as mock_parse:
            mock_parse.return_value = spec
            bridge = OpenAPIBridge()
            result = await bridge.preview_spec(config)

        assert result.title == "Test API"
        assert len(result.endpoints) == 4

    @pytest.mark.asyncio
    async def test_spec_caching(self):
        """Verify TTL cache works - same URL returns cached result."""
        spec = _make_spec()
        config = OpenAPIServiceConfig(
            name="cached",
            spec_url="https://unique-cache-test.example.com/spec.json",
        )

        # Clear cache for this test
        cache_key = str(config.spec_url)
        OpenAPIBridge._spec_cache.pop(cache_key, None)

        with patch(
            "myrm_agent_harness.toolkits.openapi_bridge.tool_generator.parse_spec_from_url",
            new_callable=AsyncMock,
        ) as mock_parse_url:
            mock_parse_url.return_value = spec

            bridge = OpenAPIBridge()
            result1 = await bridge.preview_spec(config)
            result2 = await bridge.preview_spec(config)

            # Should only parse once (second call hits cache)
            mock_parse_url.assert_called_once()
            assert result1.title == result2.title

        # Cleanup
        OpenAPIBridge._spec_cache.pop(cache_key, None)

    @pytest.mark.asyncio
    async def test_cache_expiry(self):
        """Verify cached spec is re-fetched after TTL expires."""
        spec = _make_spec()
        config = OpenAPIServiceConfig(
            name="expiry_test",
            spec_url="https://expiry-test.example.com/spec.json",
        )

        cache_key = str(config.spec_url)
        # Insert an expired entry
        OpenAPIBridge._spec_cache[cache_key] = (time.time() - 400, spec)

        with patch(
            "myrm_agent_harness.toolkits.openapi_bridge.tool_generator.parse_spec_from_url",
            new_callable=AsyncMock,
        ) as mock_parse_url:
            mock_parse_url.return_value = spec
            bridge = OpenAPIBridge()
            await bridge.preview_spec(config)

            # Should re-fetch because cache is expired
            mock_parse_url.assert_called_once()

        # Cleanup
        OpenAPIBridge._spec_cache.pop(cache_key, None)

    @pytest.mark.asyncio
    async def test_batch_error_handling(self):
        """Verify batch continues on individual service failure."""
        spec = _make_spec()
        config_ok = _make_config(name="ok_svc")
        config_bad = OpenAPIServiceConfig(name="bad_svc", spec_url="https://bad.example.com/spec.json")

        call_count = 0

        async def mock_parse(cfg):
            nonlocal call_count
            call_count += 1
            if cfg.spec_url == "https://bad.example.com/spec.json":
                raise ValueError("Parse failed")
            return spec

        with patch.object(OpenAPIBridge, "_parse_spec", side_effect=mock_parse):
            bridge = OpenAPIBridge()
            tools = await bridge.get_tools_batch([config_ok, config_bad])

        assert len(tools) == 3  # Only from ok_svc
        assert call_count == 2
