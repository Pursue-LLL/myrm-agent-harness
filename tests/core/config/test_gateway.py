import os
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from myrm_agent_harness.core.config.gateway import ToolGatewayConfig


def test_tool_gateway_config_default():
    config = ToolGatewayConfig()
    assert config.use_gateway is False
    assert config.gateway_url is None
    assert config.auth_token is None


def test_tool_gateway_config_frozen():
    config = ToolGatewayConfig()
    with pytest.raises(ValidationError):
        config.use_gateway = True


def test_tool_gateway_config_from_env_disabled():
    with patch.dict(os.environ, clear=True):
        config = ToolGatewayConfig.from_env(use_gateway=False)
        assert config.use_gateway is False
        assert config.gateway_url == "https://api.myrm.ai/v1/gateway"
        assert config.auth_token is None


def test_tool_gateway_config_from_env_enabled_success():
    with patch.dict(
        os.environ,
        {
            "MYRM_GATEWAY_URL": "https://custom.gateway.com",
            "MYRM_GATEWAY_TOKEN": "test-token",
        },
        clear=True,
    ):
        config = ToolGatewayConfig.from_env(use_gateway=True)
        assert config.use_gateway is True
        assert config.gateway_url == "https://custom.gateway.com"
        assert config.auth_token == "test-token"


def test_tool_gateway_config_from_env_enabled_missing_token():
    with patch.dict(
        os.environ,
        {"MYRM_GATEWAY_URL": "https://custom.gateway.com"},
        clear=True,
    ), pytest.raises(ValueError, match="MYRM_GATEWAY_TOKEN is required"):
        ToolGatewayConfig.from_env(use_gateway=True)


def test_tool_gateway_config_from_env_enabled_missing_url():
    with patch.dict(
        os.environ,
        {"MYRM_GATEWAY_TOKEN": "test-token"},
        clear=True,
    ):
        # Should use default URL
        config = ToolGatewayConfig.from_env(use_gateway=True)
        assert config.use_gateway is True
        assert config.gateway_url == "https://api.myrm.ai/v1/gateway"
        assert config.auth_token == "test-token"
