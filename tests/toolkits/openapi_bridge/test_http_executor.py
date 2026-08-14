"""Tests for openapi_bridge.http_executor module.

Validates HTTP request execution, path parameter substitution,
retry logic, response formatting, and auth injection.
"""

from __future__ import annotations

import json
import time
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from myrm_agent_harness.core.security.guards.ssrf import SSRFSecurityError
from myrm_agent_harness.core.security.http.secure_fetch import ContentTooLargeError
from myrm_agent_harness.core.security.types import (
    EphemeralUserCredential,
    with_user_credentials,
)
from myrm_agent_harness.toolkits.openapi_bridge.config import AuthConfig, AuthType
from myrm_agent_harness.toolkits.openapi_bridge.http_executor import OpenAPIExecutor


class TestPathResolution:
    """Test path parameter substitution."""

    def test_simple_substitution(self):
        result = OpenAPIExecutor._resolve_path("/users/{userId}", {"userId": "123"})
        assert result == "/users/123"

    def test_multiple_params(self):
        result = OpenAPIExecutor._resolve_path("/orgs/{orgId}/teams/{teamId}", {"orgId": "abc", "teamId": "xyz"})
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

        with patch(
            "myrm_agent_harness.toolkits.openapi_bridge.http_executor.secure_request",
            new_callable=AsyncMock,
            return_value=mock_response,
        ) as mock_secure_request:
            result = await executor.execute(method="GET", path="/health")

        assert '"status": "ok"' in result
        mock_secure_request.assert_awaited_once()

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

        with patch(
            "myrm_agent_harness.toolkits.openapi_bridge.http_executor.secure_request",
            new_callable=AsyncMock,
            side_effect=[error_response, success_response],
        ) as mock_secure_request:
            result = await executor.execute(method="GET", path="/data")

        assert '"data": "ok"' in result
        assert mock_secure_request.await_count == 2

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

        with patch(
            "myrm_agent_harness.toolkits.openapi_bridge.http_executor.secure_request",
            new_callable=AsyncMock,
            return_value=error_response,
        ) as mock_secure_request:
            result = await executor.execute(method="GET", path="/fail")

        assert "Error after 2 attempts" in result
        assert mock_secure_request.await_count == 2

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

        with patch(
            "myrm_agent_harness.toolkits.openapi_bridge.http_executor.secure_request",
            new_callable=AsyncMock,
            side_effect=[
                httpx.ConnectError("Connection refused"),
                success_response,
            ],
        ) as mock_secure_request:
            result = await executor.execute(method="GET", path="/data")

        assert '"ok": true' in result
        assert mock_secure_request.await_count == 2

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

        with patch(
            "myrm_agent_harness.toolkits.openapi_bridge.http_executor.secure_request",
            new_callable=AsyncMock,
            return_value=mock_response,
        ) as mock_secure_request:
            await executor.execute(method="GET", path="/protected")

        call_kwargs = mock_secure_request.call_args[1]
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

        with patch(
            "myrm_agent_harness.toolkits.openapi_bridge.http_executor.secure_request",
            new_callable=AsyncMock,
        ) as mock_secure_request:
            mock_secure_request.return_value = mock_response

            await executor.execute(
                method="POST",
                path="/users/{userId}/posts",
                path_params={"userId": "123"},
                body={"title": "Hello"},
            )

        call_args = mock_secure_request.call_args
        assert call_args is not None
        assert call_args.args[2] == "https://api.example.com/users/123/posts"
        assert call_args.kwargs["json"] == {"title": "Hello"}

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


class TestUserCredentialsInjection:
    """Test ephemeral user credential header injection and refresh paths."""

    @staticmethod
    def _make_cred(issuer: str, token: str, **kwargs: Any) -> EphemeralUserCredential:
        return EphemeralUserCredential(issuer=issuer, token=token, **kwargs)

    @pytest.mark.asyncio
    async def test_credentials_injected_with_issuer_match(self):
        executor = OpenAPIExecutor(
            base_url="https://api.example.com",
            auth_config=AuthConfig(),
            service_name="github",
            timeout=10.0,
        )
        mock_response = httpx.Response(
            200,
            headers={"content-type": "text/plain"},
            text="ok",
            request=httpx.Request("GET", "https://api.example.com/repos"),
        )
        cred = self._make_cred("github", "user-token")

        with patch(
            "myrm_agent_harness.toolkits.openapi_bridge.http_executor.secure_request",
            new_callable=AsyncMock,
            return_value=mock_response,
        ) as mock_secure_request:
            async with with_user_credentials((cred,)):
                await executor.execute(method="GET", path="/repos")

        call_kwargs = mock_secure_request.call_args[1]
        assert call_kwargs["headers"]["Authorization"] == "Bearer user-token"

    @pytest.mark.asyncio
    async def test_credentials_injected_when_issuer_in_base_url(self):
        executor = OpenAPIExecutor(
            base_url="https://github.com/api",
            auth_config=AuthConfig(),
            timeout=10.0,
        )
        mock_response = httpx.Response(
            200,
            headers={"content-type": "text/plain"},
            text="ok",
            request=httpx.Request("GET", "https://github.com/api/x"),
        )
        cred = self._make_cred("github", "pat-token")

        with patch(
            "myrm_agent_harness.toolkits.openapi_bridge.http_executor.secure_request",
            new_callable=AsyncMock,
            return_value=mock_response,
        ) as mock_secure_request:
            async with with_user_credentials((cred,)):
                await executor.execute(method="GET", path="/x")

        call_kwargs = mock_secure_request.call_args[1]
        assert call_kwargs["headers"]["Authorization"] == "Bearer pat-token"

    @pytest.mark.asyncio
    async def test_no_credentials_context_no_injection(self):
        executor = OpenAPIExecutor(
            base_url="https://api.example.com",
            auth_config=AuthConfig(),
            service_name="github",
            timeout=10.0,
        )
        mock_response = httpx.Response(
            200,
            headers={"content-type": "text/plain"},
            text="ok",
            request=httpx.Request("GET", "https://api.example.com/repos"),
        )

        with patch(
            "myrm_agent_harness.toolkits.openapi_bridge.http_executor.secure_request",
            new_callable=AsyncMock,
            return_value=mock_response,
        ) as mock_secure_request:
            await executor.execute(method="GET", path="/repos")

        call_kwargs = mock_secure_request.call_args[1]
        assert "Authorization" not in call_kwargs["headers"]

    @pytest.mark.asyncio
    async def test_expired_credential_triggers_preemptive_refresh(self):
        async def refresh() -> EphemeralUserCredential:
            return self._make_cred("github", "refreshed-token")

        executor = OpenAPIExecutor(
            base_url="https://api.example.com",
            auth_config=AuthConfig(),
            service_name="github",
            timeout=10.0,
        )
        mock_response = httpx.Response(
            200,
            headers={"content-type": "text/plain"},
            text="ok",
            request=httpx.Request("GET", "https://api.example.com/repos"),
        )
        cred = self._make_cred("github", "old-token", expires_at=time.time() - 60, refresh_callback=refresh)

        with patch(
            "myrm_agent_harness.toolkits.openapi_bridge.http_executor.secure_request",
            new_callable=AsyncMock,
            return_value=mock_response,
        ) as mock_secure_request:
            async with with_user_credentials((cred,)):
                await executor.execute(method="GET", path="/repos")

        call_kwargs = mock_secure_request.call_args[1]
        assert call_kwargs["headers"]["Authorization"] == "Bearer refreshed-token"

    @pytest.mark.asyncio
    async def test_refresh_callback_error_keeps_old_token(self):
        async def refresh() -> EphemeralUserCredential:
            raise RuntimeError("refresh failed")

        executor = OpenAPIExecutor(
            base_url="https://api.example.com",
            auth_config=AuthConfig(),
            service_name="github",
            timeout=10.0,
        )
        mock_response = httpx.Response(
            200,
            headers={"content-type": "text/plain"},
            text="ok",
            request=httpx.Request("GET", "https://api.example.com/repos"),
        )
        cred = self._make_cred("github", "old-token", expires_at=time.time() - 60, refresh_callback=refresh)

        with patch(
            "myrm_agent_harness.toolkits.openapi_bridge.http_executor.secure_request",
            new_callable=AsyncMock,
            return_value=mock_response,
        ) as mock_secure_request:
            async with with_user_credentials((cred,)):
                await executor.execute(method="GET", path="/repos")

        call_kwargs = mock_secure_request.call_args[1]
        assert call_kwargs["headers"]["Authorization"] == "Bearer old-token"

    @pytest.mark.asyncio
    async def test_401_triggers_refresh_and_retries(self):
        async def refresh() -> EphemeralUserCredential:
            return self._make_cred("github", "new-token")

        executor = OpenAPIExecutor(
            base_url="https://api.example.com",
            auth_config=AuthConfig(),
            service_name="github",
            timeout=10.0,
        )
        request = httpx.Request("GET", "https://api.example.com/repos")
        unauthorized = httpx.Response(401, headers={}, text="Unauthorized", request=request)
        success = httpx.Response(
            200,
            headers={"content-type": "application/json"},
            text='{"ok": true}',
            request=request,
        )
        cred = self._make_cred("github", "expired-token", refresh_callback=refresh)

        with patch(
            "myrm_agent_harness.toolkits.openapi_bridge.http_executor.secure_request",
            new_callable=AsyncMock,
            side_effect=[unauthorized, success],
        ) as mock_secure_request:
            async with with_user_credentials((cred,)):
                result = await executor.execute(method="GET", path="/repos")

        assert '"ok": true' in result
        assert mock_secure_request.await_count == 2
        second_call_headers = mock_secure_request.await_args_list[1].kwargs["headers"]
        assert second_call_headers["Authorization"] == "Bearer new-token"

    @pytest.mark.asyncio
    async def test_401_refresh_failure_logs_and_falls_back(self):
        async def refresh() -> EphemeralUserCredential:
            raise RuntimeError("refresh exploded")

        executor = OpenAPIExecutor(
            base_url="https://api.example.com",
            auth_config=AuthConfig(),
            service_name="github",
            timeout=10.0,
        )
        request = httpx.Request("GET", "https://api.example.com/repos")
        unauthorized = httpx.Response(401, headers={}, text="Unauthorized", request=request)
        cred = self._make_cred("github", "expired-token", refresh_callback=refresh)

        with patch(
            "myrm_agent_harness.toolkits.openapi_bridge.http_executor.secure_request",
            new_callable=AsyncMock,
            return_value=unauthorized,
        ) as mock_secure_request:
            async with with_user_credentials((cred,)):
                result = await executor.execute(method="GET", path="/repos")

        assert "Error 401" in result
        assert mock_secure_request.await_count == 1


class TestExecuteExceptions:
    """Test exception handling in request execution."""

    @pytest.mark.asyncio
    async def test_ssrf_blocked(self):
        executor = OpenAPIExecutor(
            base_url="https://api.example.com",
            auth_config=AuthConfig(),
            timeout=10.0,
        )
        with patch(
            "myrm_agent_harness.toolkits.openapi_bridge.http_executor.secure_request",
            new_callable=AsyncMock,
            side_effect=SSRFSecurityError("blocked"),
        ):
            result = await executor.execute(method="GET", path="/data")

        assert "Blocked by SSRF policy" in result

    @pytest.mark.asyncio
    async def test_response_too_large(self):
        executor = OpenAPIExecutor(
            base_url="https://api.example.com",
            auth_config=AuthConfig(),
            timeout=10.0,
        )
        with patch(
            "myrm_agent_harness.toolkits.openapi_bridge.http_executor.secure_request",
            new_callable=AsyncMock,
            side_effect=ContentTooLargeError("too big"),
        ):
            result = await executor.execute(method="GET", path="/data")

        assert "exceeded the download size limit" in result


class TestFormattingEdgeCases:
    """Test remaining response formatting branches."""

    def test_plain_text_truncated(self):
        response = httpx.Response(
            200,
            headers={"content-type": "text/plain"},
            text="x" * 5000,
        )
        result = OpenAPIExecutor._format_response(response)
        assert "truncated" in result
        assert len(result) < 4500

    def test_plain_text_error_response(self):
        response = httpx.Response(
            500,
            headers={"content-type": "text/plain"},
            text="boom",
        )
        result = OpenAPIExecutor._format_response(response)
        assert result == "Error 500: boom"
