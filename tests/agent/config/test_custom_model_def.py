"""测试CustomModelDef自定义模型定义"""

from myrm_agent_harness.agent.config.llm import CustomModelDef, LLMConfig


def test_custom_model_def_basic():
    """测试基本的CustomModelDef创建"""
    custom_def = CustomModelDef(model_id="ollama/llama3.2", context_length=8192, max_tokens=4096)

    assert custom_def.model_id == "ollama/llama3.2"
    assert custom_def.context_length == 8192
    assert custom_def.max_tokens == 4096
    assert custom_def.supports_tools is True  # 默认值
    assert custom_def.supports_streaming is True  # 默认值
    assert custom_def.supports_vision is False  # 默认值


def test_custom_model_def_with_llm_config():
    """测试CustomModelDef与LLMConfig集成"""
    custom_def = CustomModelDef(model_id="ollama/llama3.2", context_length=8192, max_tokens=4096)

    config = LLMConfig(
        model=custom_def.model_id,
        api_key="dummy",  # Ollama不需要key但LiteLLM要求
        base_url="http://localhost:11434",
        custom_model_def=custom_def,
    )

    assert config.model == "ollama/llama3.2"
    assert config.base_url == "http://localhost:11434"
    assert config.custom_model_def == custom_def
    assert config.custom_model_def.context_length == 8192


def test_custom_model_def_immutable():
    """测试CustomModelDef不可变性"""
    custom_def = CustomModelDef(model_id="ollama/llama3.2")

    # 应该抛出AttributeError（frozen=True）
    try:
        custom_def.context_length = 16384  # type: ignore[misc]
        assert False, "Should have raised AttributeError"
    except AttributeError:
        pass


def test_custom_model_def_lm_studio():
    """测试LM Studio场景"""
    custom_def = CustomModelDef(model_id="lm-studio/mistral-7b", context_length=32768, max_tokens=8192)

    config = LLMConfig(
        model=custom_def.model_id, api_key="dummy", base_url="http://localhost:1234/v1", custom_model_def=custom_def
    )

    assert config.custom_model_def.context_length == 32768
    assert config.custom_model_def.max_tokens == 8192


def test_custom_model_def_vllm():
    """测试vLLM场景"""
    custom_def = CustomModelDef(
        model_id="vllm/qwen2.5-72b",
        context_length=131072,  # Qwen2.5支持128k
        max_tokens=8192,
        supports_vision=True,  # Qwen2.5-VL支持视觉
    )

    config = LLMConfig(
        model=custom_def.model_id,
        api_key="dummy",
        base_url="http://your-vllm-server:8000/v1",
        custom_model_def=custom_def,
        supports_vision=True,  # 与custom_model_def一致
    )

    assert config.custom_model_def.context_length == 131072
    assert config.custom_model_def.supports_vision is True
    assert config.supports_vision is True


def test_llm_config_without_custom_model_def():
    """测试LLMConfig不使用custom_model_def（向后兼容）"""
    config = LLMConfig(model="gpt-4", api_key="sk-xxx", base_url=None)

    assert config.custom_model_def is None
    assert config.model == "gpt-4"
