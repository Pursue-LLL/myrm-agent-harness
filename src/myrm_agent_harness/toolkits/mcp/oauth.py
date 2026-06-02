"""MCP OAuth 2.0 + PKCE authentication provider.

Framework-level OAuth provider that implements ``MCPAuthProvider`` Protocol.
Manages token lifecycle (acquisition, caching, refresh) for remote MCP servers
requiring OAuth authorization.

The provider itself is storage-agnostic — actual token persistence is delegated
to the business layer via ``MCPOAuthTokenStore`` Protocol callbacks.

[INPUT]
- config::MCPAuthProvider (POS: the protocol this module implements)

[OUTPUT]
- MCPOAuthProvider: OAuth auth provider for remote MCP servers
- MCPOAuthTokenStore: Protocol for business-layer token persistence
- MCPOAuthToken: Token data model
- MCPOAuthConfig: Per-server OAuth configuration

[POS]
MCP OAuth 2.0 + PKCE authentication. Framework-level provider implementing
MCPAuthProvider, delegating token storage to the business layer.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import time
from base64 import urlsafe_b64encode
from typing import Protocol
from urllib.parse import urlencode

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class MCPOAuthToken(BaseModel):
    """OAuth token data model."""

    access_token: str
    token_type: str = "Bearer"
    refresh_token: str | None = None
    expires_at: float | None = None
    scope: str | None = None

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return time.time() >= self.expires_at - 30  # 30s safety margin


class MCPOAuthConfig(BaseModel):
    """Per-server OAuth configuration.

    Fields align with OAuth 2.1 / MCP RFC 9728 conventions.
    """

    authorization_endpoint: str = Field(..., description="OAuth authorization endpoint URL")
    token_endpoint: str = Field(..., description="OAuth token endpoint URL")
    client_id: str = Field(..., description="OAuth client ID")
    client_secret: str | None = Field(default=None, description="OAuth client secret (confidential clients)")
    scope: str | None = Field(default=None, description="OAuth scope string")
    redirect_uri: str = Field(
        default="http://127.0.0.1:0/callback",
        description="Redirect URI for authorization code flow",
    )


class MCPOAuthTokenStore(Protocol):
    """Protocol for business-layer OAuth token persistence.

    The framework delegates all token I/O to the business layer via this
    protocol, remaining storage-agnostic (file, DB, encrypted vault, etc.).
    """

    async def get_token(self, server_name: str) -> MCPOAuthToken | None:
        """Retrieve a cached token for the given MCP server. None if absent."""
        ...

    async def save_token(self, server_name: str, token: MCPOAuthToken) -> None:
        """Persist a token for the given MCP server."""
        ...

    async def delete_token(self, server_name: str) -> None:
        """Remove the stored token for the given MCP server."""
        ...

    async def refresh_token_exchange(
        self, server_name: str, oauth_config: MCPOAuthConfig, refresh_token: str
    ) -> MCPOAuthToken | None:
        """Exchange a refresh token for a new access token.

        Returns the new token on success, None if refresh failed (e.g. revoked).
        The implementation should also persist the new token.
        """
        ...


def generate_pkce_pair() -> tuple[str, str]:
    """Generate a PKCE code_verifier + code_challenge pair (S256).

    Returns:
        (code_verifier, code_challenge) tuple.
    """
    verifier = secrets.token_urlsafe(64)[:128]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def build_authorization_url(
    oauth_config: MCPOAuthConfig,
    state: str,
    code_challenge: str,
    redirect_uri: str,
) -> str:
    """Build the OAuth authorization URL with PKCE parameters."""
    params: dict[str, str] = {
        "response_type": "code",
        "client_id": oauth_config.client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    if oauth_config.scope:
        params["scope"] = oauth_config.scope
    return f"{oauth_config.authorization_endpoint}?{urlencode(params)}"


class MCPOAuthProvider:
    """OAuth 2.0 + PKCE authentication provider for remote MCP servers.

    Implements the ``MCPAuthProvider`` protocol. On each MCP connection attempt:
    1. Check for a cached, non-expired token → return it
    2. If token expired and has refresh_token → attempt refresh
    3. If no valid token → return empty (the business layer handles the
       interactive authorization flow via its own UI/callback mechanism)
    """

    def __init__(
        self,
        server_name: str,
        oauth_config: MCPOAuthConfig,
        token_store: MCPOAuthTokenStore,
    ) -> None:
        self._server_name = server_name
        self._oauth_config = oauth_config
        self._token_store = token_store

    @property
    def server_name(self) -> str:
        return self._server_name

    @property
    def oauth_config(self) -> MCPOAuthConfig:
        return self._oauth_config

    async def get_auth_headers(
        self, server_name: str, server_url: str
    ) -> dict[str, str]:
        """Return OAuth Authorization headers for the MCP connection.

        Attempts token retrieval from cache, refreshes if expired, and returns
        empty dict if no valid token is available (letting the server reject
        with 401, which the business layer can catch to trigger interactive auth).
        """
        token = await self._token_store.get_token(self._server_name)
        if token is None:
            return {}

        if token.is_expired:
            if token.refresh_token:
                refreshed = await self._try_refresh(token.refresh_token)
                if refreshed:
                    token = refreshed
                else:
                    await self._token_store.delete_token(self._server_name)
                    return {}
            else:
                await self._token_store.delete_token(self._server_name)
                return {}

        return {"Authorization": f"{token.token_type} {token.access_token}"}

    async def _try_refresh(self, refresh_token: str) -> MCPOAuthToken | None:
        try:
            return await self._token_store.refresh_token_exchange(
                self._server_name, self._oauth_config, refresh_token
            )
        except Exception:
            logger.warning(
                "OAuth token refresh failed for MCP server '%s'",
                self._server_name,
                exc_info=True,
            )
            return None


__all__ = [
    "MCPOAuthConfig",
    "MCPOAuthProvider",
    "MCPOAuthToken",
    "MCPOAuthTokenStore",
    "build_authorization_url",
    "generate_pkce_pair",
]
