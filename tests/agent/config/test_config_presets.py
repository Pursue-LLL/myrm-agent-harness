"""配置预设系统测试"""

import pytest

from myrm_agent_harness.agent.config import BUILTIN_PRESETS, AgentConfig, LLMConfig


def test_builtin_presets_exist():
    """测试内置预设存在"""
    assert "development" in BUILTIN_PRESETS
    assert "production" in BUILTIN_PRESETS
    assert "saas" in BUILTIN_PRESETS


def test_from_preset_development():
    """测试 development 预设"""
    llm = LLMConfig(model="gpt-4", api_key="test-key")
    config = AgentConfig.from_preset("development", llm)

    assert config.recursion_limit == 200
    assert config.enable_artifacts is True
    assert config.artifacts_output_path == "./artifacts"
    assert config.storage_config.backend_type == "local"
    assert config.storage_config.virtual_mode is True


def test_from_preset_production():
    """测试 production 预设"""
    llm = LLMConfig(model="gpt-4", api_key="test-key")
    config = AgentConfig.from_preset("production", llm)

    assert config.recursion_limit == 50
    assert config.timeout_seconds == 300
    assert config.enable_artifacts is False
    assert config.storage_config.backend_type == "local"
    assert config.storage_config.virtual_mode is True


def test_from_preset_saas():
    """测试 saas 预设"""
    llm = LLMConfig(model="gpt-4", api_key="test-key")
    config = AgentConfig.from_preset("saas", llm)

    assert config.recursion_limit == 100
    assert config.timeout_seconds == 600
    assert config.enable_artifacts is True
    assert config.artifacts_output_path == "/shared/artifacts"
    assert config.storage_config.backend_type == "custom"


def test_from_preset_with_overrides():
    """测试预设覆盖"""
    llm = LLMConfig(model="gpt-4", api_key="test-key")
    config = AgentConfig.from_preset("development", llm, recursion_limit=300)

    assert config.recursion_limit == 300  # 覆盖值
    assert config.enable_artifacts is True  # 预设值


def test_from_preset_invalid_name():
    """测试无效预设名称"""
    llm = LLMConfig(model="gpt-4", api_key="test-key")

    with pytest.raises(ValueError) as exc_info:
        AgentConfig.from_preset("invalid", llm)

    assert "Unknown preset: invalid" in str(exc_info.value)
    assert "Available:" in str(exc_info.value)


def test_from_dict():
    """测试 from_dict"""
    data = {
        "llm": {"model": "gpt-4", "api_key": "test-key"},
        "recursion_limit": 100,
        "enable_artifacts": False,
    }
    config = AgentConfig.from_dict(data)

    assert config.recursion_limit == 100
    assert config.enable_artifacts is False


def test_config_preset_immutable():
    """测试 ConfigPreset 不可变"""
    preset = BUILTIN_PRESETS["development"]

    with pytest.raises(AttributeError):
        preset.name = "new_name"
