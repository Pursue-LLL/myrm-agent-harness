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
        assert detector.needs_reasoning_content_echo(
            provider="xiaomi", model="mimo-v2.5-pro", base_url=""
        )
        assert detector.needs_reasoning_content_echo(
            provider="", model="xiaomi_mimo/mimo-v2.5-pro", base_url=""
        )
        assert detector.needs_reasoning_content_echo(
            provider="", model="", base_url="https://api.xiaomimimo.com/v1"
        )

    def test_needs_reasoning_content_echo_deepseek(self, detector):
        """DeepSeek models require reasoning_content echo-back."""
        assert detector.needs_reasoning_content_echo(
            provider="deepseek", model="deepseek-v4-flash", base_url=""
        )
        assert detector.needs_reasoning_content_echo(
            provider="", model="deepseek/deepseek-v4-pro", base_url=""
        )
        assert detector.needs_reasoning_content_echo(
            provider="custom", model="", base_url="https://api.deepseek.com/v1"
        )

    def test_needs_reasoning_content_echo_kimi(self, detector):
        """Kimi/Moonshot models require reasoning_content echo-back."""
        assert detector.needs_reasoning_content_echo(
            provider="kimi-coding", model="kimi-k2.5", base_url=""
        )
        assert detector.needs_reasoning_content_echo(
            provider="", model="moonshot/kimi-k2", base_url=""
        )
        assert detector.needs_reasoning_content_echo(
            provider="custom", model="", base_url="https://api.moonshot.ai/v1"
        )

    def test_needs_reasoning_content_echo_other(self, detector):
        """Other models do not require reasoning_content echo-back."""
        assert not detector.needs_reasoning_content_echo(
            provider="openai", model="gpt-4o", base_url=""
        )
        assert not detector.needs_reasoning_content_echo(
            provider="anthropic", model="claude-3-opus", base_url=""
        )
        assert not detector.needs_reasoning_content_echo(
            provider="", model="", base_url=""
        )

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

    def test_empty_inputs(self, detector):
        """Test empty inputs."""
        assert not detector.needs_reasoning_content_echo(provider="", model="", base_url="")
        assert not detector.is_mimo_model(provider="", model="", base_url="")
        assert not detector.is_deepseek_model(provider="", model="", base_url="")
        assert not detector.is_kimi_model(provider="", model="", base_url="")
