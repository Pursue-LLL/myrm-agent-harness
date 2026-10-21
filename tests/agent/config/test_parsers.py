"""Unit tests for agent/config/parsers.py."""

from __future__ import annotations

from myrm_agent_harness.agent.config.parsers import parse_litellm_model, to_litellm_model


class TestToLiteLLMModel:
    """Test to_litellm_model function."""

    def test_openai_model(self) -> None:
        """Test OpenAI model conversion."""
        result = to_litellm_model("openai", "gpt-4o-mini")
        assert result == "openai/gpt-4o-mini"  # OpenAI now preserves prefix

    def test_anthropic_model(self) -> None:
        """Test Anthropic model conversion."""
        result = to_litellm_model("anthropic", "claude-3-sonnet-20240229")
        assert result == "anthropic/claude-3-sonnet-20240229"

    def test_ollama_model(self) -> None:
        """Test Ollama model conversion (with provider_type)."""
        result = to_litellm_model("my_ollama", "llama3", provider_type="ollama")
        assert result == "ollama/llama3"

    def test_vllm_model(self) -> None:
        """Test vLLM model conversion (with provider_type)."""
        result = to_litellm_model("my_vllm", "qwen2.5", provider_type="vllm")
        assert result == "vllm/qwen2.5"  # vLLM provider_type returns vllm/ prefix

    def test_openai_compatible_model(self) -> None:
        """Test OpenAI-compatible model conversion."""
        result = to_litellm_model("siliconflow", "deepseek-chat", provider_type="openai_compatible")
        assert result == "openai/deepseek-chat"

    def test_openai_like_model(self) -> None:
        """Test OpenAI-like provider conversion."""
        result = to_litellm_model("basic_openai-like", "deepseek-v4-flash", provider_type="openai-like")
        assert result == "openai/deepseek-v4-flash"

    def test_default_fallback(self) -> None:
        """Test default fallback when no provider_type."""
        result = to_litellm_model("custom_provider", "custom_model")
        assert result == "custom_provider/custom_model"


class TestParseLiteLLMModel:
    """Test parse_litellm_model function."""

    def test_standard_format(self) -> None:
        """Test parsing standard provider/model format."""
        provider, model = parse_litellm_model("openai/gpt-4o-mini")
        assert provider == "openai"
        assert model == "gpt-4o-mini"

    def test_anthropic_format(self) -> None:
        """Test parsing Anthropic model."""
        provider, model = parse_litellm_model("anthropic/claude-3-sonnet-20240229")
        assert provider == "anthropic"
        assert model == "claude-3-sonnet-20240229"

    def test_ollama_format(self) -> None:
        """Test parsing Ollama model."""
        provider, model = parse_litellm_model("ollama/llama3")
        assert provider == "ollama"
        assert model == "llama3"

    def test_no_slash_defaults_to_openai(self) -> None:
        """Test that models without slash default to openai provider."""
        provider, model = parse_litellm_model("gpt-4o-mini")
        assert provider == "openai"
        assert model == "gpt-4o-mini"

    def test_multiple_slashes(self) -> None:
        """Test parsing model name with multiple slashes."""
        provider, model = parse_litellm_model("openai/custom/model/name")
        assert provider == "openai"
        assert model == "custom/model/name"


class TestRoundTrip:
    """Test round-trip conversion (to -> parse -> to)."""

    def test_roundtrip_openai(self) -> None:
        """Test OpenAI model round-trip."""
        original = "openai/gpt-4o-mini"
        provider, model = parse_litellm_model(original)  # ("openai", "gpt-4o-mini")
        result = to_litellm_model(provider, model)  # "openai/gpt-4o-mini"
        assert result == "openai/gpt-4o-mini"  # OpenAI now preserves prefix

    def test_roundtrip_anthropic(self) -> None:
        """Test Anthropic model round-trip."""
        original = "anthropic/claude-3-sonnet-20240229"
        provider, model = parse_litellm_model(original)
        result = to_litellm_model(provider, model)
        assert result == original

    def test_roundtrip_custom(self) -> None:
        """Test custom provider round-trip."""
        original = "custom_provider/custom_model"
        provider, model = parse_litellm_model(original)
        result = to_litellm_model(provider, model)
        assert result == original
