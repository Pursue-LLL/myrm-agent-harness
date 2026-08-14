"""OpenAPI Bridge Parameter Schema Extraction.

Extracts a merged per-endpoint parameter JSON Schema from OpenAPI 3.x /
Swagger 2.0 operations: path/query/header ``parameters`` plus the request body
(``requestBody`` / ``in: body``), with local ``$ref`` pointers resolved inline
so the merged schema is self-contained for LLM consumption.

[INPUT]
- .config::ParsedEndpoint (POS: endpoint metadata model)
- mcp.schema.normalize::flatten_json_schema (POS: $ref inlining utility)

[OUTPUT]
- extract_endpoint_params: (param_schema, path_keys, query_keys) for one operation

[POS]
OpenAPI Bridge parameter extraction. Pure spec-declaration → JSON Schema
conversion shared by spec_parser (per-endpoint) and tool generation.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.mcp.schema.normalize import flatten_json_schema


def extract_endpoint_params(
    operation: dict[str, object],
    path_item: dict[str, object],
    *,
    is_swagger_2: bool,
    components: dict[str, object] | None = None,
    definitions: dict[str, object] | None = None,
    top_parameters: dict[str, object] | None = None,
) -> tuple[dict[str, object] | None, set[str], set[str]]:
    """Extract a merged parameter JSON Schema for an operation.

    Merges path-level and operation-level ``parameters`` (operation wins on
    name+location collision) plus the request body (OpenAPI 3.x
    ``requestBody`` / Swagger 2.0 ``in: body``). ``$ref`` pointers are
    resolved against the document's ``components`` (OpenAPI 3.x),
    ``definitions`` (Swagger 2.0) and top-level ``parameters`` (Swagger 2.0)
    containers so the merged schema is self-contained for LLM consumption.
    Returns ``None`` when the spec declares no usable parameters.
    """
    properties: dict[str, object] = {}
    required: list[str] = []
    path_keys: set[str] = set()
    query_keys: set[str] = set()

    raw_params: dict[tuple[str, str], dict[str, object]] = {}
    for container in (path_item, operation):
        params = container.get("parameters")
        if not isinstance(params, list):
            continue
        for param in params:
            if not isinstance(param, dict):
                continue
            param = _resolve_param_ref(
                param, components, definitions, top_parameters
            )
            name = param.get("name")
            location = param.get("in")
            if not isinstance(name, str) or not name or location in ("", "header"):
                continue
            raw_params[(name, str(location))] = param

    for (name, location), param in raw_params.items():
        if location == "path":
            path_keys.add(name)
        elif location == "query":
            query_keys.add(name)
        schema = param.get("schema")
        if not isinstance(schema, dict):
            schema = {"type": str(param.get("type", "string"))}
        schema = _resolve_schema_refs(schema, components, definitions)
        properties[name] = schema
        if param.get("required") is True:
            required.append(name)

    body_schema: dict[str, object] | None = None
    if not is_swagger_2:
        request_body = operation.get("requestBody")
        if isinstance(request_body, dict):
            request_body = _resolve_request_body_ref(
                request_body, components, definitions
            )
            body_schema = _pick_json_schema(request_body)
    else:
        body_param = raw_params.get(("body", "body"))
        if body_param is not None:
            candidate = body_param.get("schema")
            if isinstance(candidate, dict):
                body_schema = candidate

    if isinstance(body_schema, dict):
        body_schema = _resolve_schema_refs(body_schema, components, definitions)
        body_type = body_schema.get("type")
        body_props = body_schema.get("properties")
        if body_type == "object" and isinstance(body_props, dict) and body_props:
            for name, prop in body_props.items():
                properties.setdefault(str(name), prop)
            body_required = body_schema.get("required")
            if isinstance(body_required, list):
                for name in body_required:
                    key = str(name)
                    if key not in required and key in properties:
                        required.append(key)
        else:
            properties["body"] = body_schema

    if not properties:
        return None, path_keys, query_keys

    schema: dict[str, object] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema, path_keys, query_keys


def _pick_json_schema(request_body: dict[str, object]) -> dict[str, object] | None:
    """Pick the first JSON-encodable schema from an OpenAPI 3.x requestBody."""
    content = request_body.get("content")
    if not isinstance(content, dict):
        return None
    media = content.get("application/json")
    if not isinstance(media, dict):
        media = content.get("*/*")
    if not isinstance(media, dict):
        for candidate in content.values():
            if isinstance(candidate, dict):
                media = candidate
                break
    if isinstance(media, dict):
        schema = media.get("schema")
        if isinstance(schema, dict):
            return schema
    return None


def _resolve_param_ref(
    param: dict[str, object],
    components: dict[str, object] | None,
    definitions: dict[str, object] | None,
    top_parameters: dict[str, object] | None = None,
) -> dict[str, object]:
    """Resolve an operation-level ``$ref`` parameter against the document containers.

    Supports OpenAPI 3.x ``#/components/parameters/X`` and Swagger 2.0
    top-level ``#/parameters/X`` pointers.
    """
    ref = param.get("$ref")
    if not isinstance(ref, str):
        return param
    root: dict[str, object] = {}
    if components is not None:
        root["components"] = components
    if definitions is not None:
        root["definitions"] = definitions
    if top_parameters is not None:
        root["parameters"] = top_parameters
    resolved = _lookup_ref_target(ref, root)
    return resolved if isinstance(resolved, dict) else param


def _resolve_request_body_ref(
    request_body: dict[str, object],
    components: dict[str, object] | None,
    definitions: dict[str, object] | None,
) -> dict[str, object]:
    """Resolve an OpenAPI 3.x ``requestBody`` ``$ref`` when present.

    Most real-world specs reuse bodies via ``#/components/requestBodies/X``;
    without resolution the operation silently loses its body schema.
    """
    ref = request_body.get("$ref")
    if not isinstance(ref, str):
        return request_body
    root: dict[str, object] = {}
    if components is not None:
        root["components"] = components
    if definitions is not None:
        root["definitions"] = definitions
    resolved = _lookup_ref_target(ref, root)
    return resolved if isinstance(resolved, dict) else request_body


def _resolve_schema_refs(
    schema: dict[str, object],
    components: dict[str, object] | None,
    definitions: dict[str, object] | None,
) -> dict[str, object]:
    """Resolve ``$ref`` pointers in a schema against the document containers."""
    if "$ref" not in schema and not _contains_ref(schema):
        return schema
    enriched = dict(schema)
    if components is not None:
        enriched["components"] = components
    if definitions is not None:
        enriched["definitions"] = definitions
    return flatten_json_schema(enriched)


def _contains_ref(node: object) -> bool:
    """Return True when a schema node (or nested children) carries a ``$ref``."""
    if isinstance(node, dict):
        if "$ref" in node:
            return True
        return any(_contains_ref(value) for value in node.values())
    if isinstance(node, list):
        return any(_contains_ref(item) for item in node)
    return False


def _lookup_ref_target(
    ref: str,
    container: dict[str, object],
) -> dict[str, object] | None:
    """Resolve a local ``#/...`` pointer against a single container dict.

    Supports ``#/components/parameters/X``, ``#/components/requestBodies/X``,
    ``#/components/schemas/X``, ``#/definitions/X``, top-level
    ``#/parameters/X`` (Swagger 2.0) and nested descent such as
    ``#/definitions/Foo/properties/bar``. Returns ``None`` when the pointer
    cannot be walked.
    """
    if not ref.startswith("#/"):
        return None
    parts = ref[2:].split("/")
    node: object = container
    for part in parts:
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node if isinstance(node, dict) else None


__all__ = ["extract_endpoint_params"]
