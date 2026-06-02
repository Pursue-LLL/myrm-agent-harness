"""Tests for openapi_bridge.http_executor module.

Validates HTTP request execution, path parameter substitution,
retry logic, response formatting, and auth injection.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from myrm_agent_harness.toolkits.openapi_bridge.config import AuthConfig, AuthType
from myrm_agent_harness.toolkits.openapi_bridge.http_executor import OpenAPIExecutor


class TestPathResolution:
    """Test path parameter substitution."""

    def test_simple_substitution(self):
        result = OpenAPIExecutor._resolve_path("/users/{userId}", {"userId": "123"})
        assert result == "/users/123"

    def test_multiple_params(self):
        result = OpenAPIExecutor._resolve_path(
            "/orgs/{orgId}/teams/{teamId}", {"orgId": "abc", "teamId": "xyz"}
        )
        assert result == "/orgs/abc/teams/xyz"

    def test_no_params(self):
        result = OpenAPIExecutor._resolve_path("/health", {})
        assert result == "/health"

    def test_missing_param_preserved(self):
        result = OpenAPIExecutor._resolve_path("/items/{itemId}", {})
        assert result == "/items/{itemId}"


class TestResponseFormatting:
    """Test response formatting logic."""

    def test_204_no_content(self):
        response = httpx.Response(204, headers={})
        result = OpenAPIExecutor._format_response(response)
        assert result == "Success (204 No Content)"

    def test_json_response(self):
        response = httpx.Response(
            200,
            headers={"content-type": "application/json"},
            text='{"name": "Rex", "type": "dog"}',
        )
        result = OpenAPIExecutor._format_response(response)
        assert '"name": "Rex"' in result
        assert '"type": "dog"' in result

    def test_error_response(self):
        response = httpx.Response(
            404,
            headers={"content-type": "application/json"},
            text='{"error": "not found"}',
        )
        result = OpenAPIExecutor._format_response(response)
        assert result.startswith("Error 404:")

    def test_large_json_truncation(self):
        large_obj = {"data": "x" * 10000}
        import json
        response = httpx.Response(
            200,
            headers={"content-type": "application/json"},
            text=json.dumps(large_obj),
        )
        result = OpenAPIExecutor._format_response(response)
        assert "truncated" in result
        assert len(result) < 9000

    def test_plain_text_response(self):
        response = httpx.Response(
            200,
            headers={"content-type": "text/plain"},
            text="Hello World",
        )
        result = OpenAPIExecutor._format_response(response)
        assert result == "Hello World"


class TestExecuteRequest:
    """Test full request execution with mocked httpx."""

    @pytest.mark.asyncio
    async def test_successful_get(self):
        executor = OpenAPIExecutor(
            base_url="https://api.example.com",
            auth_config=AuthConfig(),
            timeout=10.0,
            max_retries=0,
        )

        mock_response = httpx.Response(
            200,
            headers={"content-type": "application/json"},
            text='{"status": "ok"}',
            request=httpx.Request("GET", "https://api.example.com/health"),
        )

        with patch.object(executor, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.request.return_value = mock_response
            mock_get_client.return_value = mock_client

            result = await executor.execute(method="GET", path="/health")

        assert '"status": "ok"' in result
        mock_client.request.assert_called_once()

    @pytest.mark.asyncio
    async def test_retry_on_5xx(self):
        executor = OpenAPIExecutor(
            base_url="https://api.example.com",
            auth_config=AuthConfig(),
            timeout=10.0,
            max_retries=2,
        )

        error_response = httpx.Response(
            503,
            headers={},
            text="Service Unavailable",
            request=httpx.Request("GET", "https://api.example.com/data"),
        )
        success_response = httpx.Response(
            200,
            headers={"content-type": "application/json"},
            text='{"data": "ok"}',
            request=httpx.Request("GET", "https://api.example.com/data"),
        )

        with patch.object(executor, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.request.side_effect = [error_response, success_response]
            mock_get_client.return_value = mock_client

            result = await executor.execute(method="GET", path="/data")

        assert '"data": "ok"' in result
        assert mock_client.request.call_count == 2

    @pytest.mark.asyncio
    async def test_max_retries_exhausted(self):
        executor = OpenAPIExecutor(
            base_url="https://api.example.com",
            auth_config=AuthConfig(),
            timeout=10.0,
            max_retries=1,
        )

        error_response = httpx.Response(
            500,
            headers={},
            text="Internal Error",
            request=httpx.Request("GET", "https://api.example.com/fail"),
        )

        with patch.object(executor, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.request.return_value = error_response
            mock_get_client.return_value = mock_client

            result = await executor.execute(method="GET", path="/fail")

        assert "Error after 2 attempts" in result
        assert mock_client.request.call_count == 2

    @pytest.mark.asyncio
    async def test_network_error_retry(self):
        executor = OpenAPIExecutor(
            base_url="https://api.example.com",
            auth_config=AuthConfig(),
            timeout=10.0,
            max_retries=1,
        )

        success_response = httpx.Response(
            200,
            headers={"content-type": "application/json"},
            text='{"ok": true}',
            request=httpx.Request("GET", "https://api.example.com/data"),
        )

        with patch.object(executor, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.request.side_effect = [
                httpx.ConnectError("Connection refused"),
                success_response,
            ]
            mock_get_client.return_value = mock_client

            result = await executor.execute(method="GET", path="/data")

        assert '"ok": true' in result

    @pytest.mark.asyncio
    async def test_auth_headers_injected(self):
        auth_config = AuthConfig(type=AuthType.BEARER, bearer_token="my-token")
        executor = OpenAPIExecutor(
            base_url="https://api.example.com",
            auth_config=auth_config,
            timeout=10.0,
        )

        mock_response = httpx.Response(
            200,
            headers={"content-type": "text/plain"},
            text="ok",
            request=httpx.Request("GET", "https://api.example.com/protected"),
        )

        with patch.object(executor, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.request.return_value = mock_response
            mock_get_client.return_value = mock_client

            await executor.execute(method="GET", path="/protected")

        call_kwargs = mock_client.request.call_args[1]
        assert "Authorization" in call_kwargs["headers"]
        assert call_kwargs["headers"]["Authorization"] == "Bearer my-token"

    @pytest.mark.asyncio
    async def test_path_params_and_body(self):
        executor = OpenAPIExecutor(
            base_url="https://api.example.com",
            auth_config=AuthConfig(),
        )

        mock_response = httpx.Response(
            201,
            headers={"content-type": "application/json"},
            text='{"id": "new"}',
            request=httpx.Request("POST", "https://api.example.com/users/123/posts"),
        )

        with patch.object(executor, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.request.return_value = mock_response
            mock_get_client.return_value = mock_client

            await executor.execute(
                method="POST",
                path="/users/{userId}/posts",
                path_params={"userId": "123"},
                body={"title": "Hello"},
            )

        call_kwargs = mock_client.request.call_args[1]
        assert call_kwargs["url"] == "https://api.example.com/users/123/posts"
        assert call_kwargs["json"] == {"title": "Hello"}

    @pytest.mark.asyncio
    async def test_close(self):
        executor = OpenAPIExecutor(
            base_url="https://api.example.com",
            auth_config=AuthConfig(),
        )
        mock_client = AsyncMock()
        mock_client.is_closed = False
        executor._client = mock_client

        await executor.close()
        mock_client.aclose.assert_called_once()
        assert executor._client is None
