"""OpenAPI Bridge Authentication.

Provides authentication header injection for OpenAPI service calls.
Supports API Key, Bearer Token, Basic Auth, and OAuth2 Client Credentials.

[INPUT]
- httpx (POS: async HTTP client for OAuth2 token exchange)
- .config::AuthConfig, AuthType (POS: auth configuration models)

[OUTPUT]
- OpenAPIAuthProvider: Resolves auth config into HTTP headers for each request

[POS]
OpenAPI Bridge Authentication. Stateless auth header resolver that converts
AuthConfig into request headers. OAuth2 tokens are cached until expiry.
"""

from __future__ import annotations

import base64
import logging
import time

import httpx

from myrm_agent_harness.infra.tls_compat import create_httpx_client

from .config import AuthConfig, AuthType

logger = logging.getLogger(__name__)


class OpenAPIAuthProvider:
    """Resolves authentication configuration into HTTP headers.

    For OAuth2 client_credentials, tokens are fetched and cached until expiry.
    Thread-safe for concurrent access within a single event loop.

    Example::

        provider = OpenAPIAuthProvider(auth_config)
        headers = await provider.get_headers()
        # Use headers in httpx request
    """

    def __init__(self, config: AuthConfig) -> None:
        self._config = config
        self._oauth2_token: str | None = None
        self._oauth2_expires_at: float = 0.0

    async def get_headers(self) -> dict[str, str]:
        """Resolve authentication into HTTP headers.

        Returns:
            Dict of HTTP headers to include in the request.
            Returns empty dict for AuthType.NONE.
        """
        match self._config.type:
            case AuthType.NONE:
                return {}
            case AuthType.API_KEY:
                return self._resolve_api_key()
            case AuthType.BEARER:
                return {"Authorization": f"Bearer {self._config.bearer_token}"}
            case AuthType.BASIC:
                return self._resolve_basic()
            case AuthType.OAUTH2_CLIENT_CREDENTIALS:
                return await self._resolve_oauth2()

    def _resolve_api_key(self) -> dict[str, str]:
        """Resolve API Key authentication."""
        if self._config.api_key_location == "header":
            return {self._config.api_key_header: self._config.api_key or ""}
        # Query parameter — handled separately in http_executor
        return {}

    def get_query_params(self) -> dict[str, str]:
        """Get authentication query parameters (for api_key in query location).

        Returns:
            Dict of query params, or empty dict if not applicable.
        """
        if self._config.type == AuthType.API_KEY and self._config.api_key_location == "query":
            return {self._config.api_key_header: self._config.api_key or ""}
        return {}

    def _resolve_basic(self) -> dict[str, str]:
        """Resolve Basic authentication."""
        credentials = f"{self._config.username}:{self._config.password}"
        encoded = base64.b64encode(credentials.encode()).decode()
        return {"Authorization": f"Basic {encoded}"}

    async def _resolve_oauth2(self) -> dict[str, str]:
        """Resolve OAuth2 Client Credentials with token caching."""
        if self._oauth2_token and time.time() < self._oauth2_expires_at:
            return {"Authorization": f"Bearer {self._oauth2_token}"}

        token = await self._fetch_oauth2_token()
        return {"Authorization": f"Bearer {token}"}

    async def _fetch_oauth2_token(self) -> str:
        """Fetch a new OAuth2 access token via client_credentials grant."""
        if not self._config.token_url:
            raise ValueError("OAuth2 token_url not configured")

        data: dict[str, str] = {
            "grant_type": "client_credentials",
            "client_id": self._config.client_id or "",
            "client_secret": self._config.client_secret or "",
        }
        if self._config.scopes:
            data["scope"] = " ".join(self._config.scopes)

        async with create_httpx_client(timeout=15.0) as client:
            try:
                response = await client.post(
                    self._config.token_url,
                    data=data,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                response.raise_for_status()
            except httpx.HTTPError as e:
                logger.error("OAuth2 token fetch failed: %s", e)
                raise ValueError(f"OAuth2 token fetch failed: {e}") from e

        token_data = response.json()
        access_token = token_data.get("access_token")
        if not access_token:
            raise ValueError("OAuth2 response missing access_token")

        # Cache token with safety margin (10% before actual expiry)
        expires_in = int(token_data.get("expires_in", 3600))
        self._oauth2_token = access_token
        self._oauth2_expires_at = time.time() + (expires_in * 0.9)

        logger.info("OAuth2 token refreshed, expires in %ds", expires_in)
        return access_token


__all__ = ["OpenAPIAuthProvider"]
