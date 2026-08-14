"""OpenAPI Spec Parser.

Parses OpenAPI 3.x and Swagger 2.0 specifications into a unified intermediate
representation. Supports fetching from URL or parsing inline content (JSON/YAML).

[INPUT]
- httpx (POS: async HTTP client for fetching remote specs)
- PyYAML (POS: YAML parsing)
- .config::ParsedEndpoint (POS: endpoint metadata model)
- core.security.http.secure_fetch::secure_get / ContentTooLargeError (POS: SSRF-protected spec download with size cap)

[OUTPUT]
- ParsedSpec: Complete parsed specification with metadata and endpoints
- parse_spec_from_url: Fetch and parse a remote spec
- parse_spec_from_content: Parse inline spec content

[POS]
OpenAPI Spec Parser. Converts OpenAPI 3.x / Swagger 2.0 into a unified
ParsedSpec with endpoint grouping by tags.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Literal

import httpx
import yaml
from pydantic import BaseModel, Field

from myrm_agent_harness.toolkits.mcp.schema.normalize import flatten_json_schema

from .config import ParsedEndpoint

logger = logging.getLogger(__name__)

_HTTP_METHODS = frozenset({"get", "post", "put", "delete", "patch", "head", "options"})


class ParsedSpec(BaseModel):
    """Unified intermediate representation of a parsed OpenAPI specification.

    Attributes:
        title: API title from spec info
        version: API version from spec info
        description: API description
        base_url: Resolved base URL for API calls
        spec_version: Detected spec version (openapi_3x or swagger_2)
        endpoints: All parsed endpoints
        tags: Mapping of tag name to tag description
    """

    title: str = Field(default="Untitled API")
    version: str = Field(default="")
    description: str = Field(default="")
    base_url: str = Field(default="")
    spec_version: Literal["openapi_3x", "swagger_2"] = Field(default="openapi_3x")
    endpoints: list[ParsedEndpoint] = Field(default_factory=list)
    tags: dict[str, str] = Field(default_factory=dict)

    def get_endpoints_by_tag(self) -> dict[str, list[ParsedEndpoint]]:
        """Group endpoints by their first tag. Untagged go under 'default'."""
        groups: dict[str, list[ParsedEndpoint]] = {}
        for ep in self.endpoints:
            tag = ep.tags[0] if ep.tags else "default"
            groups.setdefault(tag, []).append(ep)
        return groups


async def parse_spec_from_url(url: str, *, timeout: float = 30.0) -> ParsedSpec:
    """Fetch and parse an OpenAPI spec from a remote URL.

    Args:
        url: URL pointing to an OpenAPI spec (JSON or YAML)
        timeout: HTTP request timeout in seconds

    Returns:
        ParsedSpec with all endpoints extracted

    Raises:
        ValueError: If the spec cannot be fetched or parsed
    """
    from myrm_agent_harness.core.security.guards.ssrf import SSRFSecurityError
    from myrm_agent_harness.core.security.http.secure_fetch import (
        ContentTooLargeError,
        secure_get,
    )

    try:
        response = await secure_get(url, timeout=timeout)
        response.raise_for_status()
    except SSRFSecurityError as e:
        raise ValueError(f"Blocked by SSRF policy: {e}") from e
    except ContentTooLargeError as e:
        raise ValueError(f"Spec too large from {url}: {e}") from e
    except httpx.HTTPStatusError as e:
        raise ValueError(f"Failed to fetch spec from {url}: HTTP {e.response.status_code}") from e
    except httpx.RequestError as e:
        raise ValueError(f"Failed to fetch spec from {url}: {e}") from e

    content = response.text
    return parse_spec_from_content(content, source_url=url)


def parse_spec_from_content(content: str, *, source_url: str = "") -> ParsedSpec:
    """Parse an OpenAPI spec from inline content (JSON or YAML string).

    Args:
        content: Spec content as JSON or YAML string
        source_url: Original URL (used for resolving relative server URLs)

    Returns:
        ParsedSpec with all endpoints extracted

    Raises:
        ValueError: If the content cannot be parsed as valid OpenAPI
    """
    spec_dict = _parse_content_to_dict(content)
    return _parse_spec_dict(spec_dict, source_url=source_url)


def _parse_content_to_dict(content: str) -> dict[str, object]:
    """Parse JSON or YAML content string into a dictionary."""
    content = content.strip()

    # Try JSON first (faster)
    if content.startswith("{"):
        try:
            result = json.loads(content)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

    # Fall back to YAML
    try:
        result = yaml.safe_load(content)
        if isinstance(result, dict):
            return result
    except yaml.YAMLError:
        pass

    raise ValueError("Content is not valid JSON or YAML")


def _parse_spec_dict(spec: dict[str, object], *, source_url: str = "") -> ParsedSpec:
    """Route parsing based on detected spec version."""
    openapi_version = spec.get("openapi", "")
    swagger_version = spec.get("swagger", "")

    if isinstance(openapi_version, str) and openapi_version.startswith("3"):
        return _parse_openapi_3x(spec, source_url=source_url)
    elif isinstance(swagger_version, str) and swagger_version.startswith("2"):
        return _parse_swagger_2(spec, source_url=source_url)
    else:
        raise ValueError(
            f"Unsupported spec version. Expected OpenAPI 3.x or Swagger 2.0, "
            f"got openapi={openapi_version!r}, swagger={swagger_version!r}"
        )


def _parse_openapi_3x(spec: dict[str, object], *, source_url: str = "") -> ParsedSpec:
    """Parse an OpenAPI 3.x specification."""
    info = spec.get("info", {})
    if not isinstance(info, dict):
        info = {}

    base_url = _resolve_base_url_3x(spec, source_url)
    tags_map = _extract_tags(spec)
    endpoints = _extract_endpoints(spec, is_swagger_2=False)

    return ParsedSpec(
        title=str(info.get("title", "Untitled API")),
        version=str(info.get("version", "")),
        description=str(info.get("description", "")),
        base_url=base_url,
        spec_version="openapi_3x",
        endpoints=endpoints,
        tags=tags_map,
    )


def _parse_swagger_2(spec: dict[str, object], *, source_url: str = "") -> ParsedSpec:
    """Parse a Swagger 2.0 specification."""
    info = spec.get("info", {})
    if not isinstance(info, dict):
        info = {}

    base_url = _resolve_base_url_2(spec, source_url)
    tags_map = _extract_tags(spec)
    endpoints = _extract_endpoints(spec, is_swagger_2=True)

    return ParsedSpec(
        title=str(info.get("title", "Untitled API")),
        version=str(info.get("version", "")),
        description=str(info.get("description", "")),
        base_url=base_url,
        spec_version="swagger_2",
        endpoints=endpoints,
        tags=tags_map,
    )


def _resolve_base_url_3x(spec: dict[str, object], source_url: str) -> str:
    """Resolve base URL from OpenAPI 3.x servers array."""
    servers = spec.get("servers")
    if isinstance(servers, list) and servers:
        first_server = servers[0]
        if isinstance(first_server, dict):
            url = str(first_server.get("url", ""))
            if url:
                # Handle relative URLs
                if url.startswith("/") and source_url:
                    from urllib.parse import urlparse

                    parsed = urlparse(source_url)
                    return f"{parsed.scheme}://{parsed.netloc}{url}"
                return url.rstrip("/")
    return ""


def _resolve_base_url_2(spec: dict[str, object], source_url: str) -> str:
    """Resolve base URL from Swagger 2.0 host/basePath/schemes."""
    host = str(spec.get("host", ""))
    base_path = str(spec.get("basePath", ""))
    schemes = spec.get("schemes")

    if not host:
        if source_url:
            from urllib.parse import urlparse

            parsed = urlparse(source_url)
            return f"{parsed.scheme}://{parsed.netloc}{base_path}".rstrip("/")
        return ""

    scheme = "https"
    if isinstance(schemes, list) and schemes:
        scheme = str(schemes[0])

    return f"{scheme}://{host}{base_path}".rstrip("/")


def _extract_tags(spec: dict[str, object]) -> dict[str, str]:
    """Extract tag name -> description mapping."""
    tags_list = spec.get("tags")
    if not isinstance(tags_list, list):
        return {}

    result: dict[str, str] = {}
    for tag in tags_list:
        if isinstance(tag, dict):
            name = str(tag.get("name", ""))
            desc = str(tag.get("description", ""))
            if name:
                result[name] = desc
    return result


def _extract_endpoints(
    spec: dict[str, object],
    *,
    is_swagger_2: bool,
) -> list[ParsedEndpoint]:
    """Extract all endpoints from paths object."""
    paths = spec.get("paths")
    if not isinstance(paths, dict):
        return []

    components = spec.get("components")
    if not isinstance(components, dict):
        components = None
    definitions = spec.get("definitions")
    if not isinstance(definitions, dict):
        definitions = None

    endpoints: list[ParsedEndpoint] = []
    seen_op_ids: set[str] = set()

    for path, path_item in paths.items():
        if not isinstance(path_item, dict) or not isinstance(path, str):
            continue

        # Path-level parameters (shared by all operations)
        for method in _HTTP_METHODS:
            operation = path_item.get(method)
            if not isinstance(operation, dict):
                continue

            operation_id = _resolve_operation_id(operation, method, path, seen_op_ids)
            seen_op_ids.add(operation_id)

            tags_raw = operation.get("tags")
            tags = [str(t) for t in tags_raw] if isinstance(tags_raw, list) else []

            summary = str(operation.get("summary", ""))
            description = str(operation.get("description", ""))
            deprecated = bool(operation.get("deprecated", False))

            param_schema, path_keys, query_keys = _extract_endpoint_params(
                operation,
                path_item,
                is_swagger_2=is_swagger_2,
                components=components,
                definitions=definitions,
            )

            endpoints.append(
                ParsedEndpoint(
                    operation_id=operation_id,
                    method=method.upper(),
                    path=path,
                    summary=summary,
                    description=description,
                    tags=tags,
                    deprecated=deprecated,
                    param_schema=param_schema,
                    path_param_keys=path_keys,
                    query_param_keys=query_keys,
                )
            )

    return endpoints


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


def _extract_endpoint_params(
    operation: dict[str, object],
    path_item: dict[str, object],
    *,
    is_swagger_2: bool,
    components: dict[str, object] | None = None,
    definitions: dict[str, object] | None = None,
) -> tuple[dict[str, object] | None, set[str], set[str]]:
    """Extract a merged parameter JSON Schema for an operation.

    Merges path-level and operation-level ``parameters`` (operation wins on
    name+location collision) plus the request body (OpenAPI 3.x
    ``requestBody`` / Swagger 2.0 ``in: body``). ``$ref`` pointers are
    resolved against the document's ``components`` (OpenAPI 3.x) or
    ``definitions`` (Swagger 2.0) containers so the merged schema is
    self-contained for LLM consumption. Returns ``None`` when the spec
    declares no usable parameters.
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
            param = _resolve_param_ref(param, components, definitions)
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


def _resolve_param_ref(
    param: dict[str, object],
    components: dict[str, object] | None,
    definitions: dict[str, object] | None,
) -> dict[str, object]:
    """Resolve an operation-level ``$ref`` parameter against the document containers."""
    ref = param.get("$ref")
    if not isinstance(ref, str):
        return param
    root: dict[str, object] = {}
    if components is not None:
        root["components"] = components
    if definitions is not None:
        root["definitions"] = definitions
    resolved = _lookup_ref_target(ref, root)
    return resolved if isinstance(resolved, dict) else param


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

    Supports ``#/components/parameters/X``, ``#/definitions/X`` and nested
    descent such as ``#/definitions/Foo/properties/bar``. Returns ``None``
    when the pointer cannot be walked.
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


def _resolve_operation_id(
    operation: dict[str, object],
    method: str,
    path: str,
    seen: set[str],
) -> str:
    """Resolve a unique operation ID for an endpoint.

    Uses the spec's operationId if available, otherwise generates one
    from method + path.
    """
    op_id = operation.get("operationId")
    if isinstance(op_id, str) and op_id.strip():
        candidate = _sanitize_operation_id(op_id.strip())
    else:
        candidate = _generate_operation_id(method, path)

    # Ensure uniqueness
    if candidate not in seen:
        return candidate

    counter = 2
    while f"{candidate}_{counter}" in seen:
        counter += 1
    return f"{candidate}_{counter}"


def _sanitize_operation_id(op_id: str) -> str:
    """Sanitize an operation ID to be a valid Python identifier."""
    sanitized = re.sub(r"[^a-zA-Z0-9_]", "_", op_id)
    sanitized = re.sub(r"_+", "_", sanitized).strip("_")
    if sanitized and sanitized[0].isdigit():
        sanitized = f"op_{sanitized}"
    return sanitized or "unnamed_operation"


def _generate_operation_id(method: str, path: str) -> str:
    """Generate an operation ID from HTTP method and path."""
    # /users/{user_id}/orders -> users_user_id_orders
    path_part = re.sub(r"\{([^}]+)\}", r"\1", path)
    path_part = re.sub(r"[^a-zA-Z0-9]", "_", path_part)
    path_part = re.sub(r"_+", "_", path_part).strip("_")
    return f"{method}_{path_part}" if path_part else method


__all__ = [
    "ParsedSpec",
    "parse_spec_from_content",
    "parse_spec_from_url",
]
