"""OpenAPI Spec Parser.

Parses OpenAPI 3.x and Swagger 2.0 specifications into a unified intermediate
representation. Supports fetching from URL or parsing inline content (JSON/YAML).

[INPUT]
- httpx (POS: async HTTP client for fetching remote specs)
- PyYAML (POS: YAML parsing)
- .config::ParsedEndpoint (POS: endpoint metadata model)

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
    from myrm_agent_harness.core.security.http.secure_fetch import secure_get

    try:
        response = await secure_get(url, timeout=timeout)
        response.raise_for_status()
    except SSRFSecurityError as e:
        raise ValueError(f"Blocked by SSRF policy: {e}") from e
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
    endpoints = _extract_endpoints(spec)

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
    endpoints = _extract_endpoints(spec)

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


def _extract_endpoints(spec: dict[str, object]) -> list[ParsedEndpoint]:
    """Extract all endpoints from paths object."""
    paths = spec.get("paths")
    if not isinstance(paths, dict):
        return []

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

            endpoints.append(
                ParsedEndpoint(
                    operation_id=operation_id,
                    method=method.upper(),
                    path=path,
                    summary=summary,
                    description=description,
                    tags=tags,
                    deprecated=deprecated,
                )
            )

    return endpoints


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
