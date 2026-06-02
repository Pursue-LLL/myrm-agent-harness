"""OpenAPI Bridge Toolkit.

Provides zero-code integration of REST APIs via OpenAPI/Swagger specifications.
Parses OpenAPI 3.x and Swagger 2.0 specs, generates LangChain StructuredTool
instances with namespace isolation, authentication injection, and endpoint selection.

Usage::

    from myrm_agent_harness.toolkits.openapi_bridge import (
        OpenAPIBridge,
        OpenAPIServiceConfig,
    )

    config = OpenAPIServiceConfig(
        name="petstore",
        spec_url="https://petstore3.swagger.io/api/v3/openapi.json",
        selected_endpoints=["findPetsByStatus", "getPetById"],
    )

    bridge = OpenAPIBridge()
    tools = await bridge.get_tools(config)
    # tools are ready for agent action space injection
"""

from .config import AuthConfig, AuthType, OpenAPIServiceConfig, ParsedEndpoint
from .http_executor import OpenAPIExecutor
from .spec_parser import ParsedSpec, parse_spec_from_content, parse_spec_from_url
from .tool_generator import OpenAPIBridge, generate_tools

__all__ = [
    "AuthConfig",
    "AuthType",
    "OpenAPIBridge",
    "OpenAPIExecutor",
    "OpenAPIServiceConfig",
    "ParsedEndpoint",
    "ParsedSpec",
    "generate_tools",
    "parse_spec_from_content",
    "parse_spec_from_url",
]
