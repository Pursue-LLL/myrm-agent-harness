"""AgentConfig Pydantic 验证测试"""

import pytest
from pydantic import ValidationError

from myrm_agent_harness.agent.config import AgentConfig, LLMConfig


def test_recursion_limit_min_validation():
    """测试 recursion_limit 最小值验证"""
    llm = LLMConfig(model="gpt-4", api_key="test-key")

    with pytest.raises(ValidationError) as exc_info:
        AgentConfig(llm=llm, recursion_limit=0)

    assert "greater than or equal to 1" in str(exc_info.value)


def test_recursion_limit_max_validation():
    """测试 recursion_limit 最大值验证"""
    llm = LLMConfig(model="gpt-4", api_key="test-key")

    with pytest.raises(ValidationError) as exc_info:
        AgentConfig(llm=llm, recursion_limit=1001)

    assert "less than or equal to 1000" in str(exc_info.value)


def test_timeout_seconds_positive_validation():
    """测试 timeout_seconds 必须为正数"""
    llm = LLMConfig(model="gpt-4", api_key="test-key")

    with pytest.raises(ValidationError) as exc_info:
        AgentConfig(llm=llm, timeout_seconds=0)

    assert "greater than 0" in str(exc_info.value)


def test_timeout_seconds_negative_validation():
    """测试 timeout_seconds 不能为负数"""
    llm = LLMConfig(model="gpt-4", api_key="test-key")

    with pytest.raises(ValidationError) as exc_info:
        AgentConfig(llm=llm, timeout_seconds=-100)

    assert "greater than 0" in str(exc_info.value)


def test_system_prompt_empty_validation():
    """测试 system_prompt 不能为空字符串"""
    llm = LLMConfig(model="gpt-4", api_key="test-key")

    with pytest.raises(ValidationError) as exc_info:
        AgentConfig(llm=llm, system_prompt="")

    assert "cannot be empty" in str(exc_info.value)


def test_system_prompt_too_large_validation():
    """测试 system_prompt 不能过大"""
    llm = LLMConfig(model="gpt-4", api_key="test-key")
    huge_prompt = "x" * 100_001

    with pytest.raises(ValidationError) as exc_info:
        AgentConfig(llm=llm, system_prompt=huge_prompt)

    assert "too large" in str(exc_info.value)


def test_valid_config():
    """测试有效配置可以正常创建"""
    llm = LLMConfig(model="gpt-4", api_key="test-key")

    config = AgentConfig(
        llm=llm,
        recursion_limit=100,
        timeout_seconds=300,
        system_prompt="You are a helpful assistant",
        enable_artifacts=True,
        artifacts_output_path="/tmp/artifacts",
    )

    assert config.recursion_limit == 100
    assert config.timeout_seconds == 300
    assert config.system_prompt == "You are a helpful assistant"


def test_default_values():
    """测试默认值正确设置"""
    llm = LLMConfig(model="gpt-4", api_key="test-key")

    config = AgentConfig(llm=llm, enable_artifacts=False)

    assert config.recursion_limit == 50
    assert config.timeout_seconds is None
    assert config.system_prompt is None
    assert config.enable_artifacts is False
    assert config.parallel_tool_calls is None


def test_from_env_backward_compatibility():
    """测试 from_env() 向后兼容性"""
    import os

    os.environ["MYRM_MODEL_NAME"] = "gpt-4"
    os.environ["MYRM_API_KEY"] = "test-key"
    os.environ["MYRM_RECURSION_LIMIT"] = "100"

    try:
        config = AgentConfig.from_env()
        assert config.llm.model == "gpt-4"
        assert config.recursion_limit == 100
    finally:
        del os.environ["MYRM_MODEL_NAME"]
        del os.environ["MYRM_API_KEY"]
        del os.environ["MYRM_RECURSION_LIMIT"]
