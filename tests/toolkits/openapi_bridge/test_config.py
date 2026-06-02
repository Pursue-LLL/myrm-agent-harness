"""Tests for openapi_bridge.config module.

Validates Pydantic model constraints, validator logic, and default values.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.openapi_bridge.config import (
    AuthConfig,
    AuthType,
    OpenAPIServiceConfig,
    ParsedEndpoint,
)


class TestAuthType:
    """Test AuthType enum values."""

    def test_enum_values(self):
        assert AuthType.NONE == "none"
        assert AuthType.API_KEY == "api_key"
        assert AuthType.BEARER == "bearer"
        assert AuthType.BASIC == "basic"
        assert AuthType.OAUTH2_CLIENT_CREDENTIALS == "oauth2_client_credentials"


class TestAuthConfig:
    """Test AuthConfig validation logic."""

    def test_default_no_auth(self):
        config = AuthConfig()
        assert config.type == AuthType.NONE

    def test_api_key_requires_key(self):
        with pytest.raises(ValueError, match="api_key is required"):
            AuthConfig(type=AuthType.API_KEY)

    def test_api_key_valid(self):
        config = AuthConfig(type=AuthType.API_KEY, api_key="my-key")
        assert config.api_key == "my-key"
        assert config.api_key_header == "X-API-Key"
        assert config.api_key_location == "header"

    def test_api_key_custom_header(self):
        config = AuthConfig(
            type=AuthType.API_KEY,
            api_key="secret",
            api_key_header="Authorization",
            api_key_location="query",
        )
        assert config.api_key_header == "Authorization"
        assert config.api_key_location == "query"

    def test_bearer_requires_token(self):
        with pytest.raises(ValueError, match="bearer_token is required"):
            AuthConfig(type=AuthType.BEARER)

    def test_bearer_valid(self):
        config = AuthConfig(type=AuthType.BEARER, bearer_token="tok_123")
        assert config.bearer_token == "tok_123"

    def test_basic_requires_username_and_password(self):
        with pytest.raises(ValueError, match="username and password are required"):
            AuthConfig(type=AuthType.BASIC, username="user")

        with pytest.raises(ValueError, match="username and password are required"):
            AuthConfig(type=AuthType.BASIC, password="pass")

    def test_basic_valid(self):
        config = AuthConfig(type=AuthType.BASIC, username="user", password="pass")
        assert config.username == "user"
        assert config.password == "pass"

    def test_oauth2_requires_all_fields(self):
        with pytest.raises(ValueError, match="token_url, client_id, and client_secret"):
            AuthConfig(type=AuthType.OAUTH2_CLIENT_CREDENTIALS, token_url="https://auth.example.com/token")

    def test_oauth2_valid(self):
        config = AuthConfig(
            type=AuthType.OAUTH2_CLIENT_CREDENTIALS,
            token_url="https://auth.example.com/token",
            client_id="cid",
            client_secret="csecret",
            scopes=["read", "write"],
        )
        assert config.token_url == "https://auth.example.com/token"
        assert config.scopes == ["read", "write"]


class TestParsedEndpoint:
    """Test ParsedEndpoint model."""

    def test_required_fields(self):
        ep = ParsedEndpoint(
            operation_id="getPets",
            method="GET",
            path="/pets",
        )
        assert ep.operation_id == "getPets"
        assert ep.method == "GET"
        assert ep.path == "/pets"
        assert ep.summary == ""
        assert ep.tags == []
        assert ep.deprecated is False

    def test_full_fields(self):
        ep = ParsedEndpoint(
            operation_id="createUser",
            method="POST",
            path="/users",
            summary="Create a new user",
            description="Creates a user account",
            tags=["users", "admin"],
            deprecated=True,
        )
        assert ep.tags == ["users", "admin"]
        assert ep.deprecated is True


class TestOpenAPIServiceConfig:
    """Test OpenAPIServiceConfig validation."""

    def test_requires_spec_source(self):
        with pytest.raises(ValueError, match="Either spec_url or spec_content"):
            OpenAPIServiceConfig(name="test")

    def test_spec_url_valid(self):
        config = OpenAPIServiceConfig(
            name="petstore",
            spec_url="https://petstore.swagger.io/v2/swagger.json",
        )
        assert config.name == "petstore"
        assert config.enabled is True
        assert config.request_timeout == 30.0
        assert config.max_retries == 2

    def test_spec_content_valid(self):
        config = OpenAPIServiceConfig(
            name="internal_api",
            spec_content='{"openapi": "3.0.0", "info": {"title": "Test", "version": "1.0"}}',
        )
        assert config.spec_content is not None
        assert config.spec_url is None

    def test_name_constraints(self):
        with pytest.raises(ValueError):
            OpenAPIServiceConfig(name="", spec_url="https://example.com/spec.json")

        with pytest.raises(ValueError):
            OpenAPIServiceConfig(name="x" * 65, spec_url="https://example.com/spec.json")

    def test_timeout_bounds(self):
        with pytest.raises(ValueError):
            OpenAPIServiceConfig(name="test", spec_url="https://x.com/s.json", request_timeout=0.5)

        with pytest.raises(ValueError):
            OpenAPIServiceConfig(name="test", spec_url="https://x.com/s.json", request_timeout=301)

    def test_max_retries_bounds(self):
        with pytest.raises(ValueError):
            OpenAPIServiceConfig(name="test", spec_url="https://x.com/s.json", max_retries=-1)

        with pytest.raises(ValueError):
            OpenAPIServiceConfig(name="test", spec_url="https://x.com/s.json", max_retries=6)

    def test_selected_endpoints(self):
        config = OpenAPIServiceConfig(
            name="api",
            spec_url="https://example.com/spec.json",
            selected_endpoints=["getUser", "createUser"],
        )
        assert config.selected_endpoints == ["getUser", "createUser"]

    def test_disabled_service(self):
        config = OpenAPIServiceConfig(
            name="disabled",
            spec_url="https://example.com/spec.json",
            enabled=False,
        )
        assert config.enabled is False
