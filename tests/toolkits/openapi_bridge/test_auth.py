"""Tests for openapi_bridge.auth module.

Validates authentication header resolution for all supported auth types
including OAuth2 token caching behavior.
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.toolkits.openapi_bridge.auth import OpenAPIAuthProvider
from myrm_agent_harness.toolkits.openapi_bridge.config import AuthConfig, AuthType


class TestNoAuth:
    """Test no-authentication mode."""

    @pytest.mark.asyncio
    async def test_returns_empty_headers(self):
        provider = OpenAPIAuthProvider(AuthConfig())
        headers = await provider.get_headers()
        assert headers == {}

    def test_returns_empty_query_params(self):
        provider = OpenAPIAuthProvider(AuthConfig())
        params = provider.get_query_params()
        assert params == {}


class TestAPIKeyAuth:
    """Test API Key authentication."""

    @pytest.mark.asyncio
    async def test_header_location(self):
        config = AuthConfig(type=AuthType.API_KEY, api_key="secret-key", api_key_header="X-API-Key")
        provider = OpenAPIAuthProvider(config)
        headers = await provider.get_headers()
        assert headers == {"X-API-Key": "secret-key"}

    @pytest.mark.asyncio
    async def test_custom_header_name(self):
        config = AuthConfig(type=AuthType.API_KEY, api_key="key123", api_key_header="Authorization")
        provider = OpenAPIAuthProvider(config)
        headers = await provider.get_headers()
        assert headers == {"Authorization": "key123"}

    @pytest.mark.asyncio
    async def test_query_location_returns_empty_headers(self):
        config = AuthConfig(type=AuthType.API_KEY, api_key="qkey", api_key_location="query")
        provider = OpenAPIAuthProvider(config)
        headers = await provider.get_headers()
        assert headers == {}

    def test_query_location_provides_params(self):
        config = AuthConfig(
            type=AuthType.API_KEY, api_key="qkey", api_key_header="api_key", api_key_location="query"
        )
        provider = OpenAPIAuthProvider(config)
        params = provider.get_query_params()
        assert params == {"api_key": "qkey"}


class TestBearerAuth:
    """Test Bearer token authentication."""

    @pytest.mark.asyncio
    async def test_bearer_header(self):
        config = AuthConfig(type=AuthType.BEARER, bearer_token="my-jwt-token")
        provider = OpenAPIAuthProvider(config)
        headers = await provider.get_headers()
        assert headers == {"Authorization": "Bearer my-jwt-token"}


class TestBasicAuth:
    """Test HTTP Basic authentication."""

    @pytest.mark.asyncio
    async def test_basic_header_encoding(self):
        config = AuthConfig(type=AuthType.BASIC, username="admin", password="secret")
        provider = OpenAPIAuthProvider(config)
        headers = await provider.get_headers()
        assert "Authorization" in headers
        assert headers["Authorization"].startswith("Basic ")

        import base64
        encoded = headers["Authorization"].split(" ")[1]
        decoded = base64.b64decode(encoded).decode()
        assert decoded == "admin:secret"


class TestOAuth2ClientCredentials:
    """Test OAuth2 Client Credentials authentication with token caching."""

    @pytest.mark.asyncio
    async def test_fetches_token(self):
        from unittest.mock import MagicMock

        config = AuthConfig(
            type=AuthType.OAUTH2_CLIENT_CREDENTIALS,
            token_url="https://auth.example.com/token",
            client_id="cid",
            client_secret="csecret",
            scopes=["read"],
        )
        provider = OpenAPIAuthProvider(config)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"access_token": "tok_abc", "expires_in": 3600}

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            headers = await provider.get_headers()

        assert headers == {"Authorization": "Bearer tok_abc"}
        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert call_args[0][0] == "https://auth.example.com/token"
        assert call_args[1]["data"]["grant_type"] == "client_credentials"
        assert call_args[1]["data"]["scope"] == "read"

    @pytest.mark.asyncio
    async def test_caches_token_until_expiry(self):
        config = AuthConfig(
            type=AuthType.OAUTH2_CLIENT_CREDENTIALS,
            token_url="https://auth.example.com/token",
            client_id="cid",
            client_secret="csecret",
        )
        provider = OpenAPIAuthProvider(config)

        # Manually set cached token
        provider._oauth2_token = "cached_token"
        provider._oauth2_expires_at = time.time() + 1000

        headers = await provider.get_headers()
        assert headers == {"Authorization": "Bearer cached_token"}

    @pytest.mark.asyncio
    async def test_refreshes_expired_token(self):
        from unittest.mock import MagicMock

        config = AuthConfig(
            type=AuthType.OAUTH2_CLIENT_CREDENTIALS,
            token_url="https://auth.example.com/token",
            client_id="cid",
            client_secret="csecret",
        )
        provider = OpenAPIAuthProvider(config)

        # Set expired cached token
        provider._oauth2_token = "expired_token"
        provider._oauth2_expires_at = time.time() - 100

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"access_token": "new_token", "expires_in": 7200}

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            headers = await provider.get_headers()

        assert headers == {"Authorization": "Bearer new_token"}

    @pytest.mark.asyncio
    async def test_token_url_missing_raises(self):
        config = AuthConfig(
            type=AuthType.OAUTH2_CLIENT_CREDENTIALS,
            token_url="https://auth.example.com/token",
            client_id="cid",
            client_secret="csecret",
        )
        provider = OpenAPIAuthProvider(config)
        # Simulate missing token_url by patching the config attribute
        with patch.object(provider._config, "token_url", None):
            with pytest.raises(ValueError, match="token_url not configured"):
                await provider.get_headers()
