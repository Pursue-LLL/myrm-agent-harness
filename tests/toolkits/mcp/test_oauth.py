"""Tests for MCP OAuth 2.0 + PKCE authentication provider.

Covers:
- MCPOAuthToken model (expiry logic, safety margin)
- MCPOAuthConfig model (validation, defaults)
- PKCE pair generation (format, uniqueness, S256 correctness)
- build_authorization_url (parameter encoding, scope handling)
- MCPOAuthProvider (token caching, refresh, header generation)
"""

from __future__ import annotations

import hashlib
import time
from base64 import urlsafe_b64encode
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

import pytest

from myrm_agent_harness.toolkits.mcp.oauth import (
    MCPOAuthConfig,
    MCPOAuthProvider,
    MCPOAuthToken,
    build_authorization_url,
    generate_pkce_pair,
)

# ---------------------------------------------------------------------------
# MCPOAuthToken model
# ---------------------------------------------------------------------------

class TestMCPOAuthToken:
    def test_not_expired_when_no_expires_at(self) -> None:
        token = MCPOAuthToken(access_token="abc")
        assert not token.is_expired

    def test_not_expired_when_future(self) -> None:
        token = MCPOAuthToken(access_token="abc", expires_at=time.time() + 3600)
        assert not token.is_expired

    def test_expired_when_past(self) -> None:
        token = MCPOAuthToken(access_token="abc", expires_at=time.time() - 10)
        assert token.is_expired

    def test_expired_within_safety_margin(self) -> None:
        """Token within 30s of expiry should be treated as expired."""
        token = MCPOAuthToken(access_token="abc", expires_at=time.time() + 20)
        assert token.is_expired

    def test_not_expired_just_outside_margin(self) -> None:
        """Token 31s before expiry should not be expired."""
        token = MCPOAuthToken(access_token="abc", expires_at=time.time() + 31)
        assert not token.is_expired

    def test_default_token_type(self) -> None:
        token = MCPOAuthToken(access_token="abc")
        assert token.token_type == "Bearer"

    def test_model_dump_roundtrip(self) -> None:
        token = MCPOAuthToken(
            access_token="abc",
            refresh_token="def",
            expires_at=1234567890.0,
            scope="read write",
        )
        data = token.model_dump()
        restored = MCPOAuthToken(**data)
        assert restored.access_token == token.access_token
        assert restored.refresh_token == token.refresh_token
        assert restored.expires_at == token.expires_at


# ---------------------------------------------------------------------------
# MCPOAuthConfig model
# ---------------------------------------------------------------------------

class TestMCPOAuthConfig:
    def test_required_fields(self) -> None:
        cfg = MCPOAuthConfig(
            authorization_endpoint="https://auth.example.com/authorize",
            token_endpoint="https://auth.example.com/token",
            client_id="my-client",
        )
        assert cfg.authorization_endpoint == "https://auth.example.com/authorize"
        assert cfg.client_secret is None
        assert cfg.scope is None

    def test_default_redirect_uri(self) -> None:
        cfg = MCPOAuthConfig(
            authorization_endpoint="https://a.com/auth",
            token_endpoint="https://a.com/token",
            client_id="cid",
        )
        assert cfg.redirect_uri == "http://127.0.0.1:0/callback"

    def test_custom_redirect_uri(self) -> None:
        cfg = MCPOAuthConfig(
            authorization_endpoint="https://a.com/auth",
            token_endpoint="https://a.com/token",
            client_id="cid",
            redirect_uri="https://myapp.com/callback",
        )
        assert cfg.redirect_uri == "https://myapp.com/callback"


# ---------------------------------------------------------------------------
# PKCE pair generation
# ---------------------------------------------------------------------------

class TestGeneratePkcePair:
    def test_returns_tuple_of_two_strings(self) -> None:
        verifier, challenge = generate_pkce_pair()
        assert isinstance(verifier, str)
        assert isinstance(challenge, str)

    def test_verifier_length_within_spec(self) -> None:
        """RFC 7636 requires 43-128 characters."""
        verifier, _ = generate_pkce_pair()
        assert 43 <= len(verifier) <= 128

    def test_challenge_is_s256_of_verifier(self) -> None:
        verifier, challenge = generate_pkce_pair()
        expected_digest = hashlib.sha256(verifier.encode("ascii")).digest()
        expected_challenge = urlsafe_b64encode(expected_digest).rstrip(b"=").decode("ascii")
        assert challenge == expected_challenge

    def test_uniqueness(self) -> None:
        pairs = [generate_pkce_pair() for _ in range(10)]
        verifiers = [p[0] for p in pairs]
        assert len(set(verifiers)) == 10

    def test_challenge_uses_url_safe_base64(self) -> None:
        """No +, /, or = characters in challenge."""
        _, challenge = generate_pkce_pair()
        assert "+" not in challenge
        assert "/" not in challenge
        assert "=" not in challenge


# ---------------------------------------------------------------------------
# build_authorization_url
# ---------------------------------------------------------------------------

class TestBuildAuthorizationUrl:
    @pytest.fixture
    def oauth_config(self) -> MCPOAuthConfig:
        return MCPOAuthConfig(
            authorization_endpoint="https://auth.example.com/authorize",
            token_endpoint="https://auth.example.com/token",
            client_id="test-client",
            scope="read write",
        )

    def test_includes_required_params(self, oauth_config: MCPOAuthConfig) -> None:
        url = build_authorization_url(
            oauth_config=oauth_config,
            state="test-state",
            code_challenge="test-challenge",
            redirect_uri="https://app.com/callback",
        )
        parsed = urlparse(url)
        params = parse_qs(parsed.query)

        assert parsed.scheme == "https"
        assert parsed.netloc == "auth.example.com"
        assert params["response_type"] == ["code"]
        assert params["client_id"] == ["test-client"]
        assert params["state"] == ["test-state"]
        assert params["code_challenge"] == ["test-challenge"]
        assert params["code_challenge_method"] == ["S256"]
        assert params["redirect_uri"] == ["https://app.com/callback"]
        assert params["scope"] == ["read write"]

    def test_omits_scope_when_none(self) -> None:
        cfg = MCPOAuthConfig(
            authorization_endpoint="https://auth.example.com/authorize",
            token_endpoint="https://auth.example.com/token",
            client_id="cid",
        )
        url = build_authorization_url(
            oauth_config=cfg,
            state="s",
            code_challenge="c",
            redirect_uri="https://app.com/cb",
        )
        params = parse_qs(urlparse(url).query)
        assert "scope" not in params


# ---------------------------------------------------------------------------
# MCPOAuthProvider
# ---------------------------------------------------------------------------

class TestMCPOAuthProvider:
    @pytest.fixture
    def mock_store(self) -> AsyncMock:
        store = AsyncMock()
        store.get_token = AsyncMock(return_value=None)
        store.save_token = AsyncMock()
        store.delete_token = AsyncMock()
        store.refresh_token_exchange = AsyncMock(return_value=None)
        return store

    @pytest.fixture
    def oauth_config(self) -> MCPOAuthConfig:
        return MCPOAuthConfig(
            authorization_endpoint="https://auth.example.com/authorize",
            token_endpoint="https://auth.example.com/token",
            client_id="cid",
        )

    @pytest.fixture
    def provider(self, oauth_config: MCPOAuthConfig, mock_store: AsyncMock) -> MCPOAuthProvider:
        return MCPOAuthProvider(
            server_name="test-mcp",
            oauth_config=oauth_config,
            token_store=mock_store,
        )

    @pytest.mark.asyncio
    async def test_no_token_returns_empty_headers(
        self, provider: MCPOAuthProvider, mock_store: AsyncMock
    ) -> None:
        headers = await provider.get_auth_headers("test-mcp", "https://mcp.example.com")
        assert headers == {}
        mock_store.get_token.assert_called_once_with("test-mcp")

    @pytest.mark.asyncio
    async def test_valid_token_returns_bearer_header(
        self, provider: MCPOAuthProvider, mock_store: AsyncMock
    ) -> None:
        mock_store.get_token.return_value = MCPOAuthToken(
            access_token="valid-access-token",
            expires_at=time.time() + 3600,
        )
        headers = await provider.get_auth_headers("test-mcp", "https://mcp.example.com")
        assert headers == {"Authorization": "Bearer valid-access-token"}

    @pytest.mark.asyncio
    async def test_expired_token_without_refresh_deletes_and_returns_empty(
        self, provider: MCPOAuthProvider, mock_store: AsyncMock
    ) -> None:
        mock_store.get_token.return_value = MCPOAuthToken(
            access_token="expired",
            expires_at=time.time() - 100,
        )
        headers = await provider.get_auth_headers("test-mcp", "https://mcp.example.com")
        assert headers == {}
        mock_store.delete_token.assert_called_once_with("test-mcp")

    @pytest.mark.asyncio
    async def test_expired_token_with_refresh_success(
        self, provider: MCPOAuthProvider, mock_store: AsyncMock, oauth_config: MCPOAuthConfig
    ) -> None:
        expired_token = MCPOAuthToken(
            access_token="expired",
            refresh_token="refresh-xyz",
            expires_at=time.time() - 100,
        )
        new_token = MCPOAuthToken(
            access_token="fresh-access",
            expires_at=time.time() + 3600,
        )
        mock_store.get_token.return_value = expired_token
        mock_store.refresh_token_exchange.return_value = new_token

        headers = await provider.get_auth_headers("test-mcp", "https://mcp.example.com")

        assert headers == {"Authorization": "Bearer fresh-access"}
        mock_store.refresh_token_exchange.assert_called_once_with(
            "test-mcp", oauth_config, "refresh-xyz"
        )

    @pytest.mark.asyncio
    async def test_expired_token_with_refresh_failure_deletes(
        self, provider: MCPOAuthProvider, mock_store: AsyncMock
    ) -> None:
        expired_token = MCPOAuthToken(
            access_token="expired",
            refresh_token="bad-refresh",
            expires_at=time.time() - 100,
        )
        mock_store.get_token.return_value = expired_token
        mock_store.refresh_token_exchange.return_value = None

        headers = await provider.get_auth_headers("test-mcp", "https://mcp.example.com")
        assert headers == {}
        mock_store.delete_token.assert_called_once_with("test-mcp")

    @pytest.mark.asyncio
    async def test_refresh_exception_returns_empty_and_deletes(
        self, provider: MCPOAuthProvider, mock_store: AsyncMock
    ) -> None:
        expired_token = MCPOAuthToken(
            access_token="expired",
            refresh_token="crash-refresh",
            expires_at=time.time() - 100,
        )
        mock_store.get_token.return_value = expired_token
        mock_store.refresh_token_exchange.side_effect = RuntimeError("network error")

        headers = await provider.get_auth_headers("test-mcp", "https://mcp.example.com")
        assert headers == {}
        mock_store.delete_token.assert_called_once_with("test-mcp")

    def test_server_name_property(self, provider: MCPOAuthProvider) -> None:
        assert provider.server_name == "test-mcp"

    def test_oauth_config_property(
        self, provider: MCPOAuthProvider, oauth_config: MCPOAuthConfig
    ) -> None:
        assert provider.oauth_config is oauth_config

    @pytest.mark.asyncio
    async def test_custom_token_type_in_header(
        self, provider: MCPOAuthProvider, mock_store: AsyncMock
    ) -> None:
        mock_store.get_token.return_value = MCPOAuthToken(
            access_token="abc",
            token_type="DPoP",
            expires_at=time.time() + 3600,
        )
        headers = await provider.get_auth_headers("test-mcp", "https://mcp.example.com")
        assert headers == {"Authorization": "DPoP abc"}
