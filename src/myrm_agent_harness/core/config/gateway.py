"""Tool Gateway configuration — framework-agnostic gateway config.

Provides ToolGatewayConfig for routing third-party tool requests (Search, Image Gen, TTS, Browser)
through the Control Plane's Unified Tool Gateway, enabling zero-config BYOK fallback.
"""

from __future__ import annotations

import os

from pydantic import BaseModel, Field


class ToolGatewayConfig(BaseModel):
    """Tool Gateway configuration.

    Defines whether a specific tool should route its traffic through the Unified Tool Gateway
    and provides the necessary gateway URL and authentication token (VirtualKey or PAT).

    Environment variables (MYRM_GATEWAY_ prefix):
    - MYRM_GATEWAY_URL: Base URL of the Unified Tool Gateway (e.g., https://control-plane.myrm.ai/tool-relay)
    - MYRM_GATEWAY_TOKEN: Authentication token (VirtualKey for SaaS, PAT for Local/Desktop)

    Example:
        >>> config = ToolGatewayConfig(use_gateway=True, gateway_url="...", auth_token="...")
    """

    use_gateway: bool = Field(
        default=False,
        description="Whether to route this tool's traffic through the Unified Tool Gateway",
    )
    gateway_url: str | None = Field(
        default=None,
        description="Base URL of the Unified Tool Gateway (required if use_gateway is True)",
    )
    auth_token: str | None = Field(
        default=None,
        description="Authentication token for the gateway (VirtualKey or PAT, required if use_gateway is True)",
    )

    model_config = {
        "frozen": True,
    }

    @classmethod
    def from_env(cls, use_gateway: bool = False) -> ToolGatewayConfig:
        """Load gateway config from MYRM_GATEWAY_* environment variables.

        Args:
            use_gateway: Whether the gateway should be enabled for this specific tool.

        Raises:
            ValueError: If use_gateway is True but gateway_url or auth_token is missing.
        """
        gateway_url = os.getenv("MYRM_GATEWAY_URL", "https://api.myrm.ai/v1/gateway")
        auth_token = os.getenv("MYRM_GATEWAY_TOKEN")

        if use_gateway:
            if not gateway_url:
                raise ValueError("MYRM_GATEWAY_URL is required when use_gateway is True")
            if not auth_token:
                raise ValueError("MYRM_GATEWAY_TOKEN is required when use_gateway is True")

        return cls(
            use_gateway=use_gateway,
            gateway_url=gateway_url,
            auth_token=auth_token,
        )
