"""Tests for ModelCapabilityDetector."""

import pytest

from myrm_agent_harness.toolkits.llms.adapters.model_capability import ModelCapabilityDetector


@pytest.fixture
def detector():
    return ModelCapabilityDetector()


class TestModelCapabilityDetector:
    """Test model capability detection."""

    def test_needs_reasoning_content_echo_mimo(self, detector):
        """MiMo models require reasoning_content echo-back."""
        assert detector.needs_reasoning_content_echo(provider="xiaomi", model="mimo-v2.5-pro", base_url="")
        assert detector.needs_reasoning_content_echo(provider="", model="xiaomi_mimo/mimo-v2.5-pro", base_url="")
        assert detector.needs_reasoning_content_echo(provider="", model="", base_url="https://api.xiaomimimo.com/v1")

    def test_needs_reasoning_content_echo_deepseek(self, detector):
        """DeepSeek models require reasoning_content echo-back."""
        assert detector.needs_reasoning_content_echo(provider="deepseek", model="deepseek-v4-flash", base_url="")
        assert detector.needs_reasoning_content_echo(provider="", model="deepseek/deepseek-v4-pro", base_url="")
        assert detector.needs_reasoning_content_echo(
            provider="custom", model="", base_url="https://api.deepseek.com/v1"
        )

    def test_needs_reasoning_content_echo_kimi(self, detector):
        """Kimi/Moonshot models require reasoning_content echo-back."""
        assert detector.needs_reasoning_content_echo(provider="kimi-coding", model="kimi-k2.5", base_url="")
        assert detector.needs_reasoning_content_echo(provider="", model="moonshot/kimi-k2", base_url="")
        assert detector.needs_reasoning_content_echo(provider="custom", model="", base_url="https://api.moonshot.ai/v1")

    def test_deepseek_through_openai_like_gateway(self, detector):
        """DeepSeek via openai-like gateways keeps model-name detection.

        Regression: `openai-like/deepseek-v4-flash` (console-gateway) is neither
        provider "deepseek", a "deepseek/" prefix, nor an api.deepseek.com host,
        so reasoning_content echo-back was skipped and replays returned HTTP 400.
        """
        assert detector.needs_reasoning_content_echo(
            provider="openai-like", model="deepseek-v4-flash", base_url="https://gateway.example/v1"
        )
        assert detector.is_deepseek_model(
            provider="openai-like", model="deepseek-v4-flash", base_url="https://gateway.example/v1"
        )
        assert detector.is_deepseek_model(
            provider="openai", model="openai/deepseek-v4-flash", base_url="https://gateway.example/v1"
        )

    def test_kimi_through_other_gateway(self, detector):
        """Kimi model-name detection works regardless of the gateway host."""
        assert detector.is_kimi_model(provider="openai-like", model="kimi-k2.5", base_url="https://gateway.example/v1")
        assert detector.is_mimo_model(
            provider="openai-like", model="mimo-v2.5-pro", base_url="https://gateway.example/v1"
        )

    def test_needs_reasoning_content_echo_other(self, detector):
        """Other models do not require reasoning_content echo-back."""
        assert not detector.needs_reasoning_content_echo(provider="openai", model="gpt-4o", base_url="")
        assert not detector.needs_reasoning_content_echo(provider="anthropic", model="claude-3-opus", base_url="")
        assert not detector.needs_reasoning_content_echo(provider="", model="", base_url="")

    def test_is_mimo_model(self, detector):
        """Test MiMo model detection."""
        assert detector.is_mimo_model(provider="xiaomi", model="", base_url="")
        assert detector.is_mimo_model(provider="mimo", model="", base_url="")
        assert detector.is_mimo_model(provider="", model="xiaomi_mimo/mimo-v2.5-pro", base_url="")
        assert detector.is_mimo_model(provider="", model="mimo/mimo-v2.5", base_url="")
        assert detector.is_mimo_model(provider="", model="", base_url="https://api.xiaomimimo.com/v1")
        assert not detector.is_mimo_model(provider="openai", model="gpt-4o", base_url="")

    def test_is_deepseek_model(self, detector):
        """Test DeepSeek model detection."""
        assert detector.is_deepseek_model(provider="deepseek", model="", base_url="")
        assert detector.is_deepseek_model(provider="", model="deepseek/deepseek-v4-flash", base_url="")
        assert detector.is_deepseek_model(provider="custom", model="", base_url="https://api.deepseek.com/v1")
        assert not detector.is_deepseek_model(provider="openai", model="gpt-4o", base_url="")

    def test_is_kimi_model(self, detector):
        """Test Kimi/Moonshot model detection."""
        assert detector.is_kimi_model(provider="kimi-coding", model="", base_url="")
        assert detector.is_kimi_model(provider="kimi-coding-cn", model="", base_url="")
        assert detector.is_kimi_model(provider="", model="moonshot/kimi-k2", base_url="")
        assert detector.is_kimi_model(provider="", model="kimi/kimi-k2.5", base_url="")
        assert detector.is_kimi_model(provider="custom", model="", base_url="https://api.moonshot.ai/v1")
        assert detector.is_kimi_model(provider="custom", model="", base_url="https://api.moonshot.cn/v1")
        assert detector.is_kimi_model(provider="custom", model="", base_url="https://api.kimi.com/v1")
        assert not detector.is_kimi_model(provider="openai", model="gpt-4o", base_url="")

    def test_case_insensitive(self, detector):
        """Test case insensitive detection."""
        assert detector.is_mimo_model(provider="XIAOMI", model="", base_url="")
        assert detector.is_deepseek_model(provider="DEEPSEEK", model="", base_url="")
        assert detector.is_kimi_model(provider="KIMI-CODING", model="", base_url="")

    def test_is_local_endpoint_and_grammar_transport(self, detector):
        """Test local/edge endpoint detection for grammar constraint transport."""
        assert detector.is_local_endpoint(provider="ollama", model="qwen2.5:7b", base_url="")
        assert detector.is_local_endpoint(provider="", model="ollama/qwen2.5-coder", base_url="")
        assert detector.is_local_endpoint(provider="openai-like", model="qwen2.5-7b-instruct", base_url="http://127.0.0.1:8000/v1")
        assert detector.is_local_endpoint(provider="", model="llama-server-qwen", base_url="http://localhost:8080/v1")
        assert detector.is_local_endpoint(provider="vllm", model="meta-llama/Llama-3.1-8B-Instruct", base_url="http://0.0.0.0:8000/v1")
        assert detector.supports_json_schema_constrained_tool_calls(
            provider="ollama", model="qwen2.5:7b", base_url="http://127.0.0.1:11434/v1"
        )
        assert not detector.is_local_endpoint(
            provider="openai", model="gpt-4o", base_url="https://api.openai.com/v1"
        )
        assert not detector.supports_json_schema_constrained_tool_calls(
            provider="anthropic", model="claude-3-7-sonnet-20250219", base_url="https://api.anthropic.com/v1"
        )

    def test_empty_inputs(self, detector):
        """Test empty inputs."""
        assert not detector.needs_reasoning_content_echo(provider="", model="", base_url="")
        assert not detector.is_mimo_model(provider="", model="", base_url="")
        assert not detector.is_deepseek_model(provider="", model="", base_url="")
        assert not detector.is_kimi_model(provider="", model="", base_url="")

    def test_is_local_weak_endpoint(self, detector):
        """Test local weak endpoint detection for grammar/schema transport."""
        assert detector.is_local_weak_endpoint(provider="ollama", model="", base_url="")
        assert detector.is_local_weak_endpoint(provider="vllm", model="", base_url="")
        assert detector.is_local_weak_endpoint(provider="llama-cpp", model="", base_url="")
        assert detector.is_local_weak_endpoint(provider="", model="ollama/qwen2.5-coder:7b", base_url="")
        assert detector.is_local_weak_endpoint(provider="", model="local/gemma-2-9b", base_url="")
        assert detector.is_local_weak_endpoint(provider="openai-like", model="qwen", base_url="http://127.0.0.1:8000/v1")
        assert detector.is_local_weak_endpoint(provider="openai-like", model="qwen", base_url="http://localhost:11434/v1")
        assert detector.is_local_weak_endpoint(provider="openai-like", model="qwen", base_url="http://llama-server:8080/v1")
        assert detector.supports_grammar_constrained_tool_calls(provider="ollama", model="", base_url="")
        assert detector.supports_grammar_constrained_tool_calls(provider="openai-like", model="qwen", base_url="http://127.0.0.1:8000/v1")
        assert not detector.is_local_weak_endpoint(provider="openai", model="gpt-4o", base_url="https://api.openai.com/v1")
        assert not detector.is_local_weak_endpoint(provider="anthropic", model="claude-3-7-sonnet", base_url="https://api.anthropic.com/v1")
        assert not detector.supports_grammar_constrained_tool_calls(provider="openai", model="gpt-4o", base_url="https://api.openai.com/v1")
