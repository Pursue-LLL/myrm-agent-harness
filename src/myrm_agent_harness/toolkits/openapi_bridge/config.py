"""OpenAPI Bridge Configuration Models.

Defines the configuration schema for OpenAPI service integration.
Business layer stores these configs per-agent; the framework uses them
to parse specs and generate tools.

[INPUT]
- (none)

[OUTPUT]
- OpenAPIServiceConfig: Per-service configuration (URL, auth, endpoint selection)
- AuthConfig: Authentication configuration for API calls
- AuthType: Enum of supported auth methods
- ParsedEndpoint: Lightweight endpoint metadata from spec parsing

[POS]
OpenAPI Bridge Configuration. Provides typed config models for spec source,
authentication, and endpoint selection.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class AuthType(StrEnum):
    """Supported authentication methods for OpenAPI services."""

    NONE = "none"
    API_KEY = "api_key"
    BEARER = "bearer"
    BASIC = "basic"
    OAUTH2_CLIENT_CREDENTIALS = "oauth2_client_credentials"


class AuthConfig(BaseModel):
    """Authentication configuration for an OpenAPI service.

    Attributes:
        type: Authentication method
        api_key: API key value (for api_key type)
        api_key_header: Header name for API key (default: X-API-Key)
        api_key_location: Where to send the key (header/query)
        bearer_token: Bearer token value (for bearer type)
        username: Username (for basic type)
        password: Password (for basic type)
        token_url: OAuth2 token endpoint (for oauth2_client_credentials)
        client_id: OAuth2 client ID
        client_secret: OAuth2 client secret
        scopes: OAuth2 scopes to request
    """

    type: AuthType = Field(default=AuthType.NONE, description="Authentication method")

    api_key: str | None = Field(default=None, description="API key value")
    api_key_header: str = Field(default="X-API-Key", description="Header name for API key")
    api_key_location: Literal["header", "query"] = Field(
        default="header", description="Where to send the API key"
    )

    bearer_token: str | None = Field(default=None, description="Bearer token")

    username: str | None = Field(default=None, description="Basic auth username")
    password: str | None = Field(default=None, description="Basic auth password")

    token_url: str | None = Field(default=None, description="OAuth2 token endpoint URL")
    client_id: str | None = Field(default=None, description="OAuth2 client ID")
    client_secret: str | None = Field(default=None, description="OAuth2 client secret")
    scopes: list[str] = Field(default_factory=list, description="OAuth2 scopes")

    @model_validator(mode="after")
    def _validate_auth_fields(self) -> AuthConfig:
        if self.type == AuthType.API_KEY and not self.api_key:
            raise ValueError("api_key is required when type is 'api_key'")
        if self.type == AuthType.BEARER and not self.bearer_token:
            raise ValueError("bearer_token is required when type is 'bearer'")
        if self.type == AuthType.BASIC and (not self.username or not self.password):
            raise ValueError("username and password are required when type is 'basic'")
        if self.type == AuthType.OAUTH2_CLIENT_CREDENTIALS and (
            not self.token_url or not self.client_id or not self.client_secret
        ):
            raise ValueError(
                "token_url, client_id, and client_secret are required for oauth2_client_credentials"
            )
        return self


class ParsedEndpoint(BaseModel):
    """Lightweight endpoint metadata extracted from an OpenAPI spec.

    Used for frontend display and user selection before tool generation.
    """

    operation_id: str = Field(..., description="Unique operation identifier")
    method: str = Field(..., description="HTTP method (GET, POST, etc.)")
    path: str = Field(..., description="URL path template (e.g. /users/{id})")
    summary: str = Field(default="", description="Short endpoint description")
    description: str = Field(default="", description="Full endpoint description")
    tags: list[str] = Field(default_factory=list, description="OpenAPI tags for grouping")
    deprecated: bool = Field(default=False, description="Whether endpoint is deprecated")


class OpenAPIServiceConfig(BaseModel):
    """Configuration for a single OpenAPI service integration.

    Stored in Agent metadata as part of `openapi_services` list.

    Attributes:
        name: Unique service identifier (used as tool namespace prefix)
        spec_url: URL to fetch the OpenAPI spec from
        spec_content: Inline spec content (JSON/YAML string, alternative to spec_url)
        base_url: Base URL override for API calls (if different from spec servers)
        auth: Authentication configuration
        selected_endpoints: List of operation_ids to expose as tools (empty = all)
        enabled: Whether this service is active
        description: Human-readable service description
        request_timeout: Per-request timeout in seconds
        max_retries: Number of retries on transient failures
    """

    name: str = Field(..., min_length=1, max_length=64, description="Unique service identifier")
    spec_url: str | None = Field(default=None, description="URL to fetch OpenAPI spec")
    spec_content: str | None = Field(default=None, description="Inline spec JSON/YAML content")
    base_url: str | None = Field(default=None, description="Base URL override for API calls")
    auth: AuthConfig = Field(default_factory=AuthConfig, description="Authentication config")
    selected_endpoints: list[str] = Field(
        default_factory=list,
        description="Operation IDs to expose (empty = all)",
    )
    enabled: bool = Field(default=True, description="Whether service is active")
    description: str = Field(default="", description="Human-readable description")
    request_timeout: float = Field(
        default=30.0, ge=1.0, le=300.0, description="Per-request timeout (seconds)"
    )
    max_retries: int = Field(default=2, ge=0, le=5, description="Max retries on transient failures")

    @model_validator(mode="after")
    def _validate_spec_source(self) -> OpenAPIServiceConfig:
        if not self.spec_url and not self.spec_content:
            raise ValueError("Either spec_url or spec_content must be provided")
        return self


__all__ = [
    "AuthConfig",
    "AuthType",
    "OpenAPIServiceConfig",
    "ParsedEndpoint",
]
