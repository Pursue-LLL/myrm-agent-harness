"""Tests for openapi_bridge.param_schema module.

Validates the edge-case branches of extract_endpoint_params: malformed
parameter entries, request-body media fallbacks, and unresolvable refs.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.openapi_bridge.param_schema import (
    _lookup_ref_target,
    extract_endpoint_params,
)


def _empty_operation() -> dict[str, object]:
    return {"operationId": "op", "responses": {"200": {"description": "OK"}}}


class TestParameterSanitization:
    """Test parameter skipping and classification edge cases."""

    def test_non_dict_param_entry_skipped(self):
        operation = _empty_operation()
        operation["parameters"] = ["not-a-dict", {"name": "q", "in": "query", "schema": {"type": "string"}}]
        schema, path_keys, query_keys = extract_endpoint_params(
            operation, {}, is_swagger_2=False
        )
        assert "q" in (schema or {}).get("properties", {})
        assert query_keys == {"q"}
        assert path_keys == set()

    def test_header_param_and_empty_name_skipped(self):
        operation = _empty_operation()
        operation["parameters"] = [
            {"name": "X-Auth", "in": "header", "schema": {"type": "string"}},
            {"name": "", "in": "query", "schema": {"type": "string"}},
        ]
        schema, _, query_keys = extract_endpoint_params(operation, {}, is_swagger_2=False)
        assert schema is None
        assert query_keys == set()

    def test_empty_param_list_returns_none(self):
        schema, _, _ = extract_endpoint_params(_empty_operation(), {}, is_swagger_2=False)
        assert schema is None


class TestRequestBodyFallbacks:
    """Test request-body media selection fallbacks."""

    def test_content_not_dict_ignored(self):
        operation = _empty_operation()
        operation["requestBody"] = {"content": ["not-a-dict"]}
        schema, _, _ = extract_endpoint_params(operation, {}, is_swagger_2=False)
        assert schema is None

    def test_wildcard_media_fallback(self):
        operation = _empty_operation()
        operation["requestBody"] = {
            "content": {"*/*": {"schema": {"type": "string"}}}
        }
        schema, _, _ = extract_endpoint_params(operation, {}, is_swagger_2=False)
        body_prop = schema["properties"]["body"]
        assert body_prop.get("type") == "string"

    def test_non_json_media_fallback(self):
        operation = _empty_operation()
        operation["requestBody"] = {
            "content": {"application/xml": {"schema": {"type": "object"}}}
        }
        schema, _, _ = extract_endpoint_params(operation, {}, is_swagger_2=False)
        assert "body" in schema["properties"]

    def test_media_without_schema_ignored(self):
        operation = _empty_operation()
        operation["requestBody"] = {"content": {"application/json": {}}}
        schema, _, _ = extract_endpoint_params(operation, {}, is_swagger_2=False)
        assert schema is None


class TestRefEdgeCases:
    """Test ref resolution edge cases."""

    def test_unresolvable_pointer_returns_none(self):
        assert _lookup_ref_target("#/components/schemas/Missing", {}) is None

    def test_non_local_ref_returns_none(self):
        assert _lookup_ref_target("https://example.com/schema.json#/X", {}) is None

    def test_nested_pointer_missing_branch_returns_none(self):
        container = {"components": {"schemas": {"A": {"properties": {"b": {"type": "string"}}}}}}
        assert _lookup_ref_target("#/components/schemas/A/properties/c", container) is None

    def test_nested_pointer_non_dict_returns_none(self):
        container = {"components": {"schemas": {"A": "not-a-dict"}}}
        assert _lookup_ref_target("#/components/schemas/A", container) is None

    def test_schema_ref_to_components_schemas_inlined(self):
        operation = _empty_operation()
        operation["requestBody"] = {
            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Order"}}}
        }
        components = {
            "schemas": {"Order": {"type": "object", "properties": {"id": {"type": "integer"}}}}
        }
        schema, _, _ = extract_endpoint_params(
            operation, {}, is_swagger_2=False, components=components
        )
        assert "$ref" not in repr(schema)
        assert "id" in schema["properties"]

    def test_request_body_ref_to_missing_bucket_degrades(self):
        operation = _empty_operation()
        operation["requestBody"] = {"$ref": "#/components/requestBodies/OrderBody"}
        schema, _, _ = extract_endpoint_params(operation, {}, is_swagger_2=False)
        assert schema is None
