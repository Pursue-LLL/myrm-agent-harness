"""OpenAPI Bridge Tool Generator.

Converts parsed OpenAPI endpoints into LangChain StructuredTool instances
with namespace isolation, parameter constraint propagation, and proper descriptions.

[INPUT]
- langchain_core.tools::StructuredTool (POS: LangChain tool factory)
- .spec_parser::ParsedSpec (POS: parsed spec intermediate representation)
- .http_executor::OpenAPIExecutor (POS: HTTP request executor)
- .config::OpenAPIServiceConfig, ParsedEndpoint (POS: configuration models)

[OUTPUT]
- generate_tools: Convert OpenAPIServiceConfig + ParsedSpec into list[BaseTool]
- OpenAPIBridge: High-level facade for spec parsing and tool generation

[POS]
OpenAPI Bridge Tool Generator. The core conversion engine that transforms
OpenAPI endpoints into LangChain tools with namespace isolation.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, ClassVar

from langchain_core.tools import BaseTool, StructuredTool

from .config import OpenAPIServiceConfig, ParsedEndpoint
from .http_executor import OpenAPIExecutor
from .spec_parser import ParsedSpec, parse_spec_from_content, parse_spec_from_url

logger = logging.getLogger(__name__)

_PATH_PARAM_PATTERN = re.compile(r"\{(\w+)\}")


async def generate_tools(
    config: OpenAPIServiceConfig,
    spec: ParsedSpec,
) -> list[BaseTool]:
    """Generate LangChain tools from an OpenAPI service configuration.

    Each selected endpoint becomes a StructuredTool with:
    - Namespaced name: {service_name}_{operation_id}
    - Description from endpoint summary/description
    - Parameters extracted from path/query/body schema
    - Bound to an OpenAPIExecutor for actual HTTP calls

    Args:
        config: Service configuration with auth and endpoint selection
        spec: Parsed spec with resolved endpoints

    Returns:
        List of LangChain StructuredTool instances ready for agent use
    """
    base_url = config.base_url or spec.base_url
    if not base_url:
        raise ValueError(f"No base URL available for service '{config.name}'")

    executor = OpenAPIExecutor(
        base_url=base_url,
        auth_config=config.auth,
        service_name=config.name,
        timeout=config.request_timeout,
        max_retries=config.max_retries,
    )

    # Filter endpoints based on selection
    endpoints = spec.endpoints
    if config.selected_endpoints:
        selected_set = set(config.selected_endpoints)
        endpoints = [ep for ep in endpoints if ep.operation_id in selected_set]

    tools: list[BaseTool] = []
    for endpoint in endpoints:
        if endpoint.deprecated:
            continue

        tool = _create_tool_for_endpoint(config.name, endpoint, executor, spec)
        if tool:
            tools.append(tool)

    logger.info(
        "Generated %d tools for OpenAPI service '%s' (%d endpoints available)",
        len(tools), config.name, len(spec.endpoints),
    )
    return tools


def _create_tool_for_endpoint(
    service_name: str,
    endpoint: ParsedEndpoint,
    executor: OpenAPIExecutor,
    spec: ParsedSpec,
) -> BaseTool | None:
    """Create a single StructuredTool for an endpoint."""
    tool_name = f"{service_name}_{endpoint.operation_id}"

    # Build description
    description = _build_description(endpoint)
    if not description:
        description = f"{endpoint.method} {endpoint.path}"

    # Extract parameters from path
    path_params = _extract_path_params(endpoint.path)

    # Build the tool function
    method = endpoint.method
    path = endpoint.path

    async def _execute_endpoint(**kwargs: Any) -> str:
        # Separate path params from body/query params
        p_params: dict[str, str] = {}
        q_params: dict[str, str] = {}
        body: dict[str, Any] | None = None

        for key, value in kwargs.items():
            if key in path_params:
                p_params[key] = str(value)
            elif key == "_body" or key == "request_body":
                if isinstance(value, dict):
                    body = value
                elif isinstance(value, str):
                    try:
                        body = json.loads(value)
                    except json.JSONDecodeError:
                        body = {"data": value}
            else:
                # For GET/DELETE: query params; for POST/PUT/PATCH: body fields
                if method in ("GET", "HEAD", "OPTIONS", "DELETE"):
                    q_params[key] = str(value)
                else:
                    if body is None:
                        body = {}
                    body[key] = value

        return await executor.execute(
            method=method,
            path=path,
            path_params=p_params or None,
            query_params=q_params or None,
            body=body,
        )

    # Build parameter schema for LLM
    param_schema = _build_param_schema(endpoint, path_params)

    try:
        tool = StructuredTool.from_function(
            func=lambda **kwargs: None,
            coroutine=_execute_endpoint,
            name=tool_name,
            description=description,
            args_schema=None,
        )
        # Manually set args_schema as dict for tools with dynamic params
        if param_schema:
            tool.args_schema = param_schema  # type: ignore[assignment]
        return tool
    except Exception as e:
        logger.warning("Failed to create tool for %s: %s", tool_name, e)
        return None


def _build_description(endpoint: ParsedEndpoint) -> str:
    """Build a concise tool description from endpoint metadata."""
    parts: list[str] = []

    if endpoint.summary:
        parts.append(endpoint.summary)
    elif endpoint.description:
        # Take first sentence/line
        first_line = endpoint.description.split("\n")[0].strip()
        if len(first_line) > 200:
            first_line = first_line[:200] + "..."
        parts.append(first_line)

    parts.append(f"[{endpoint.method} {endpoint.path}]")

    return " ".join(parts)


def _extract_path_params(path: str) -> set[str]:
    """Extract parameter names from a path template."""
    return set(_PATH_PARAM_PATTERN.findall(path))


def _build_param_schema(
    endpoint: ParsedEndpoint,
    path_params: set[str],
) -> dict[str, Any] | None:
    """Build a JSON Schema for the tool's parameters.

    Combines path parameters (always required) with method-appropriate params.
    """
    properties: dict[str, Any] = {}
    required: list[str] = []

    for param_name in sorted(path_params):
        properties[param_name] = {
            "type": "string",
            "description": f"Path parameter: {param_name}",
        }
        required.append(param_name)

    if not properties:
        return None

    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
    }
    if required:
        schema["required"] = required

    return schema


class OpenAPIBridge:
    """High-level facade for OpenAPI service integration.

    Handles the full flow: config → parse spec → generate tools.
    Includes TTL-based spec caching to avoid redundant remote fetches.

    Example::

        bridge = OpenAPIBridge()
        tools = await bridge.get_tools(config)
    """

    _spec_cache: ClassVar[dict[str, tuple[float, ParsedSpec]]] = {}
    _CACHE_TTL_SECONDS: float = 300.0

    async def get_tools(self, config: OpenAPIServiceConfig) -> list[BaseTool]:
        """Parse spec and generate tools from an OpenAPI service config.

        Args:
            config: Complete service configuration

        Returns:
            List of LangChain tools ready for agent use

        Raises:
            ValueError: If spec cannot be parsed or no base URL available
        """
        spec = await self._parse_spec(config)
        return await generate_tools(config, spec)

    async def get_tools_batch(self, configs: list[OpenAPIServiceConfig]) -> list[BaseTool]:
        """Generate tools from multiple OpenAPI service configs.

        Args:
            configs: List of service configurations

        Returns:
            Combined list of tools from all enabled services
        """
        all_tools: list[BaseTool] = []
        for cfg in configs:
            if not cfg.enabled:
                continue
            try:
                tools = await self.get_tools(cfg)
                all_tools.extend(tools)
            except Exception as e:
                logger.error("Failed to generate tools for service '%s': %s", cfg.name, e)
        return all_tools

    async def preview_spec(self, config: OpenAPIServiceConfig) -> ParsedSpec:
        """Parse and return spec metadata without generating tools.

        Used by frontend for endpoint preview/selection.
        """
        return await self._parse_spec(config)

    @classmethod
    async def _parse_spec(cls, config: OpenAPIServiceConfig) -> ParsedSpec:
        """Parse spec from URL or inline content with TTL caching."""
        import time

        cache_key = config.spec_url or hash(config.spec_content or "")
        cache_key_str = str(cache_key)

        cached = cls._spec_cache.get(cache_key_str)
        if cached:
            timestamp, spec = cached
            if time.time() - timestamp < cls._CACHE_TTL_SECONDS:
                return spec

        if config.spec_url:
            spec = await parse_spec_from_url(config.spec_url)
        elif config.spec_content:
            spec = parse_spec_from_content(config.spec_content)
        else:
            raise ValueError("No spec source configured")

        cls._spec_cache[cache_key_str] = (time.time(), spec)
        return spec


__all__ = [
    "OpenAPIBridge",
    "generate_tools",
]
