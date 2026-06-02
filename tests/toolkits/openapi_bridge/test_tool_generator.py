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
            ParsedEndpoint(
                operation_id="createPet", method="POST", path="/pets", summary="Create pet"
            ),
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
        spec = ParsedSpec(title="T", version="1", base_url="", endpoints=[
            ParsedEndpoint(operation_id="op", method="GET", path="/x", summary="X"),
        ])
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
        ) as MockExecutorCls:
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
        ) as MockExecutorCls:
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
        config_disabled = OpenAPIServiceConfig(
            name="disabled", spec_url="https://x.com/s.json", enabled=False
        )

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
        config_bad = OpenAPIServiceConfig(
            name="bad_svc", spec_url="https://bad.example.com/spec.json"
        )

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
