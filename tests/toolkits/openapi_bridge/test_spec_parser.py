"""Tests for openapi_bridge.spec_parser module.

Validates parsing of OpenAPI 3.x and Swagger 2.0 specs, tag extraction,
operation ID resolution, and error handling.
"""

from __future__ import annotations

import json

import pytest

from myrm_agent_harness.toolkits.openapi_bridge.spec_parser import (
    parse_spec_from_content,
)

OPENAPI_3_SPEC = json.dumps({
    "openapi": "3.0.3",
    "info": {"title": "Pet Store", "version": "1.0.0", "description": "A pet store API"},
    "servers": [{"url": "https://api.petstore.io/v1"}],
    "tags": [
        {"name": "pets", "description": "Pet operations"},
        {"name": "store", "description": "Store operations"},
    ],
    "paths": {
        "/pets": {
            "get": {
                "operationId": "listPets",
                "summary": "List all pets",
                "tags": ["pets"],
                "parameters": [{"name": "limit", "in": "query", "schema": {"type": "integer"}}],
                "responses": {"200": {"description": "OK"}},
            },
            "post": {
                "operationId": "createPet",
                "summary": "Create a pet",
                "tags": ["pets"],
                "requestBody": {"content": {"application/json": {"schema": {"type": "object"}}}},
                "responses": {"201": {"description": "Created"}},
            },
        },
        "/pets/{petId}": {
            "get": {
                "operationId": "getPetById",
                "summary": "Get a pet by ID",
                "tags": ["pets"],
                "parameters": [{"name": "petId", "in": "path", "required": True, "schema": {"type": "string"}}],
                "responses": {"200": {"description": "OK"}},
            },
            "delete": {
                "operationId": "deletePet",
                "summary": "Delete a pet",
                "tags": ["pets"],
                "deprecated": True,
                "responses": {"204": {"description": "Deleted"}},
            },
        },
        "/store/inventory": {
            "get": {
                "operationId": "getInventory",
                "summary": "Get store inventory",
                "tags": ["store"],
                "responses": {"200": {"description": "OK"}},
            },
        },
    },
})

SWAGGER_2_SPEC = json.dumps({
    "swagger": "2.0",
    "info": {"title": "Legacy API", "version": "2.0.0", "description": "A legacy Swagger 2.0 API"},
    "host": "api.legacy.io",
    "basePath": "/v2",
    "schemes": ["https"],
    "tags": [{"name": "users", "description": "User management"}],
    "paths": {
        "/users": {
            "get": {
                "operationId": "listUsers",
                "summary": "List users",
                "tags": ["users"],
                "responses": {"200": {"description": "OK"}},
            },
            "post": {
                "operationId": "createUser",
                "summary": "Create user",
                "tags": ["users"],
                "parameters": [{"name": "body", "in": "body", "schema": {"type": "object"}}],
                "responses": {"201": {"description": "Created"}},
            },
        },
        "/users/{userId}": {
            "get": {
                "operationId": "getUserById",
                "summary": "Get user by ID",
                "tags": ["users"],
                "parameters": [{"name": "userId", "in": "path", "required": True, "type": "string"}],
                "responses": {"200": {"description": "OK"}},
            },
        },
    },
})


class TestParseOpenAPI3:
    """Test OpenAPI 3.x parsing."""

    def test_basic_metadata(self):
        spec = parse_spec_from_content(OPENAPI_3_SPEC)
        assert spec.title == "Pet Store"
        assert spec.version == "1.0.0"
        assert spec.description == "A pet store API"
        assert spec.spec_version == "openapi_3x"
        assert spec.base_url == "https://api.petstore.io/v1"

    def test_endpoint_count(self):
        spec = parse_spec_from_content(OPENAPI_3_SPEC)
        assert len(spec.endpoints) == 5

    def test_endpoint_details(self):
        spec = parse_spec_from_content(OPENAPI_3_SPEC)
        ep_map = {ep.operation_id: ep for ep in spec.endpoints}

        assert "listPets" in ep_map
        assert ep_map["listPets"].method == "GET"
        assert ep_map["listPets"].path == "/pets"
        assert ep_map["listPets"].summary == "List all pets"
        assert ep_map["listPets"].tags == ["pets"]

        assert "createPet" in ep_map
        assert ep_map["createPet"].method == "POST"

    def test_deprecated_endpoint(self):
        spec = parse_spec_from_content(OPENAPI_3_SPEC)
        ep_map = {ep.operation_id: ep for ep in spec.endpoints}
        assert ep_map["deletePet"].deprecated is True

    def test_tags_extraction(self):
        spec = parse_spec_from_content(OPENAPI_3_SPEC)
        assert "pets" in spec.tags
        assert spec.tags["pets"] == "Pet operations"
        assert "store" in spec.tags

    def test_get_endpoints_by_tag(self):
        spec = parse_spec_from_content(OPENAPI_3_SPEC)
        by_tag = spec.get_endpoints_by_tag()
        assert "pets" in by_tag
        assert len(by_tag["pets"]) == 4
        assert "store" in by_tag
        assert len(by_tag["store"]) == 1

    def test_relative_server_url(self):
        spec_dict = {
            "openapi": "3.0.0",
            "info": {"title": "T", "version": "1"},
            "servers": [{"url": "/api/v1"}],
            "paths": {},
        }
        spec = parse_spec_from_content(
            json.dumps(spec_dict),
            source_url="https://example.com/docs/openapi.json",
        )
        assert spec.base_url == "https://example.com/api/v1"


class TestParseSwagger2:
    """Test Swagger 2.0 parsing."""

    def test_basic_metadata(self):
        spec = parse_spec_from_content(SWAGGER_2_SPEC)
        assert spec.title == "Legacy API"
        assert spec.version == "2.0.0"
        assert spec.spec_version == "swagger_2"
        assert spec.base_url == "https://api.legacy.io/v2"

    def test_endpoint_count(self):
        spec = parse_spec_from_content(SWAGGER_2_SPEC)
        assert len(spec.endpoints) == 3

    def test_endpoint_details(self):
        spec = parse_spec_from_content(SWAGGER_2_SPEC)
        ep_map = {ep.operation_id: ep for ep in spec.endpoints}

        assert "listUsers" in ep_map
        assert ep_map["listUsers"].method == "GET"
        assert ep_map["listUsers"].path == "/users"

        assert "getUserById" in ep_map
        assert ep_map["getUserById"].path == "/users/{userId}"

    def test_base_url_without_host_fallback_to_source(self):
        spec_dict = {
            "swagger": "2.0",
            "info": {"title": "T", "version": "1"},
            "basePath": "/api",
            "paths": {},
        }
        spec = parse_spec_from_content(
            json.dumps(spec_dict),
            source_url="https://internal.corp/docs/swagger.json",
        )
        assert spec.base_url == "https://internal.corp/api"


class TestOperationIdResolution:
    """Test operation ID generation and deduplication."""

    def test_auto_generated_operation_id(self):
        spec_json = json.dumps({
            "openapi": "3.0.0",
            "info": {"title": "T", "version": "1"},
            "paths": {
                "/items": {
                    "get": {"summary": "List items", "responses": {"200": {"description": "OK"}}},
                    "post": {"summary": "Create item", "responses": {"201": {"description": "OK"}}},
                },
            },
        })
        spec = parse_spec_from_content(spec_json)
        ids = [ep.operation_id for ep in spec.endpoints]
        assert "get_items" in ids
        assert "post_items" in ids

    def test_sanitize_special_characters(self):
        spec_json = json.dumps({
            "openapi": "3.0.0",
            "info": {"title": "T", "version": "1"},
            "paths": {
                "/foo": {
                    "get": {"operationId": "get-foo.bar/baz", "responses": {"200": {"description": "OK"}}},
                },
            },
        })
        spec = parse_spec_from_content(spec_json)
        assert spec.endpoints[0].operation_id == "get_foo_bar_baz"

    def test_duplicate_operation_id_dedup(self):
        spec_json = json.dumps({
            "openapi": "3.0.0",
            "info": {"title": "T", "version": "1"},
            "paths": {
                "/a": {"get": {"operationId": "getItem", "responses": {"200": {"description": "OK"}}}},
                "/b": {"get": {"operationId": "getItem", "responses": {"200": {"description": "OK"}}}},
            },
        })
        spec = parse_spec_from_content(spec_json)
        ids = [ep.operation_id for ep in spec.endpoints]
        assert "getItem" in ids
        assert "getItem_2" in ids


class TestContentParsing:
    """Test JSON/YAML content parsing."""

    def test_json_content(self):
        spec = parse_spec_from_content(OPENAPI_3_SPEC)
        assert spec.title == "Pet Store"

    def test_yaml_content(self):
        yaml_content = """
openapi: "3.0.0"
info:
  title: YAML API
  version: "1.0"
paths:
  /health:
    get:
      operationId: healthCheck
      summary: Health check
      responses:
        "200":
          description: OK
"""
        spec = parse_spec_from_content(yaml_content)
        assert spec.title == "YAML API"
        assert len(spec.endpoints) == 1
        assert spec.endpoints[0].operation_id == "healthCheck"

    def test_invalid_content_raises(self):
        with pytest.raises(ValueError, match="not valid JSON or YAML"):
            parse_spec_from_content("not a valid spec !!!")

    def test_unsupported_version_raises(self):
        with pytest.raises(ValueError, match="Unsupported spec version"):
            parse_spec_from_content(json.dumps({"info": {"title": "T"}}))


class TestSSRFProtection:
    """Test SSRF protection in parse_spec_from_url."""

    @pytest.mark.asyncio
    async def test_blocks_internal_ip(self):
        from myrm_agent_harness.toolkits.openapi_bridge.spec_parser import (
            parse_spec_from_url,
        )

        with pytest.raises(ValueError, match="Blocked by SSRF policy"):
            await parse_spec_from_url("http://169.254.169.254/latest/meta-data/")

    @pytest.mark.asyncio
    async def test_blocks_localhost(self):
        from myrm_agent_harness.toolkits.openapi_bridge.spec_parser import (
            parse_spec_from_url,
        )

        with pytest.raises(ValueError, match="Blocked by SSRF policy"):
            await parse_spec_from_url("http://127.0.0.1/api/spec")
